"""Map SCAYLE Admin API order JSON into the engine's per-customer schema.

SCAYLE returns nested JSON: the buyer under ``customer``, addresses with ``street`` / ``zipCode`` /
``countryCode``, and monetary amounts as objects (``cost.withTax`` and friends). We re-map each
order into the dict ``scoring.shopify.flatten_order`` already reads and reuse ``orders_to_customers``
— the scoring engine itself stays identical across data sources.

Two things to confirm against a real instance (scayle.dev is a client-rendered SPA, so the exact
schema was not scrapable):
  1. Field names — the mapping tolerates the likely variants (street/address1, zipCode/zip/postalCode,
     countryCode/country{code}, orderNumber/number, items/lineItems/products, firstName/first_name).
  2. Money convention — SCAYLE typically returns integer **minor units** (cents). ``_amount`` treats
     an integer amount as minor units (÷100) and a float/decimal string as already major. If a live
     instance returns major-unit integers, flip ``_MINOR_UNITS``.
"""
from __future__ import annotations

from scoring.shopify import orders_to_customers

# SCAYLE money is integer minor units (cents) by convention; set False if an instance differs.
_MINOR_UNITS = True


def _name(*parts) -> str:
    return " ".join(p for p in parts if p).strip()


def _first(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _country(addr: dict):
    c = _first(addr, "countryCode", "country_code", "country")
    if isinstance(c, dict):
        return c.get("code") or c.get("name")
    return c


def _to_major(x):
    """Integer amount -> major units (SCAYLE minor-unit convention); pass floats/strings through."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x / 100 if _MINOR_UNITS else x
    return x


def _amount(o: dict, *keys):
    """Pull a monetary amount from an order, handling SCAYLE ``{withTax/amount/value}`` objects."""
    for k in keys:
        v = o.get(k)
        if v is None:
            continue
        if isinstance(v, dict):
            inner = _first(v, "withTax", "amount", "value", "withoutTax", "gross")
            if inner is not None:
                return _to_major(inner)
            continue
        return _to_major(v)
    return None


def _street(addr: dict):
    """address1 from SCAYLE's split street fields (street + houseNumber) or a flat line."""
    flat = _first(addr, "address1", "addressLine1", "line1")
    if flat:
        return flat
    return _name(_first(addr, "street", "address"), addr.get("houseNumber")) or None


def scayle_order_to_rest(o: dict) -> dict:
    """Map one SCAYLE order to the Shopify-REST shape flatten_order expects."""
    bill = o.get("billingAddress") or o.get("invoiceAddress") or {}
    ship = o.get("shippingAddress") or o.get("deliveryAddress") or {}
    cust = o.get("customer") or o.get("buyer") or {}
    email = _first(cust, "email") or _first(bill, "email")
    first = _first(cust, "firstName", "first_name") or _first(bill, "firstName", "first_name")
    last = _first(cust, "lastName", "last_name") or _first(bill, "lastName", "last_name")
    phone = _first(bill, "phone", "phoneNumber") or _first(cust, "phone", "phoneNumber")
    full_name = _name(first, last)
    lines = o.get("items") or o.get("lineItems") or o.get("products") or []
    return {
        "id": _first(o, "id", "orderNumber", "number"),
        "status": _first(o, "status", "statusName"),
        "email": email,
        "phone": phone,
        "customer": {
            "id": _first(cust, "id") or email,
            "email": email,
            "first_name": first,
            "last_name": last,
            "phone": phone,
        },
        "total_price": _amount(o, "cost", "total", "grandTotal", "price", "totalGross"),
        "total_discounts": _amount(o, "discount", "totalDiscount", "discountTotal"),
        "created_at": _first(o, "createdAt", "orderedAt", "orderDate", "created_at"),
        "note": _first(o, "note", "comment", "customerComment"),
        "tags": "",  # SCAYLE orders carry no Shopify-style tags
        "line_items": [{"quantity": (ln or {}).get("quantity")} for ln in lines if ln],
        "billing_address": {
            "name": _name(_first(bill, "firstName", "first_name"),
                          _first(bill, "lastName", "last_name")) or full_name,
            "company": _first(bill, "companyName", "company"),
            "address1": _street(bill),
            "address2": _first(bill, "address2", "additional", "addressLine2"),
            "city": bill.get("city"),
            "country": _country(bill),
            "zip": _first(bill, "zipCode", "zip", "postalCode"),
            "phone": phone,
        },
        "shipping_address": {
            "name": _name(_first(ship, "firstName", "first_name"),
                          _first(ship, "lastName", "last_name")) or full_name,
            "address1": _street(ship),
            "address2": _first(ship, "address2", "additional", "addressLine2"),
            "city": ship.get("city"),
            "country": _country(ship),
            "zip": _first(ship, "zipCode", "zip", "postalCode"),
        },
    }


def scayle_orders_to_customers(orders: list[dict], today=None):
    """SCAYLE orders -> one scored-ready row per customer (reuses the engine)."""
    return orders_to_customers([scayle_order_to_rest(o) for o in orders], today=today)
