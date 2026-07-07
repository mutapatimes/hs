"""Map Centra GraphQL order nodes into the engine's per-customer schema.

Centra's Integration API returns nested GraphQL objects: money as ``grandTotal.value``, country
as an object with a ``code``, the buyer split across ``customer`` and the billing address. We
re-map each order into the dict ``scoring.shopify.flatten_order`` already reads and reuse
``orders_to_customers`` — the scoring engine itself stays identical across data sources.

The mapping is deliberately tolerant of the schema spellings that vary between Centra versions
(``zip`` / ``zipCode`` / ``zipcode``, ``phoneNumber`` / ``phone``, ``companyName`` / ``company``,
``address1`` / ``address``): whichever the fetch query selects, the adapter reads it.
"""
from __future__ import annotations

from scoring.shopify import orders_to_customers


def _name(*parts) -> str:
    return " ".join(p for p in parts if p).strip()


def _first(d: dict, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _country(addr: dict):
    c = addr.get("country")
    if isinstance(c, dict):
        return c.get("code") or c.get("name")
    return c


def _money(v):
    if isinstance(v, dict):
        return v.get("value")
    return v


def centra_order_to_rest(o: dict) -> dict:
    """Map one Centra order node to the Shopify-REST shape flatten_order expects."""
    bill = o.get("billingAddress") or {}
    ship = o.get("shippingAddress") or {}
    cust = o.get("customer") or o.get("buyer") or {}
    email = _first(cust, "email") or _first(bill, "email")
    first = _first(cust, "firstName", "first_name") or _first(bill, "firstName", "first_name")
    last = _first(cust, "lastName", "last_name") or _first(bill, "lastName", "last_name")
    phone = (_first(bill, "phoneNumber", "phone") or _first(cust, "phoneNumber", "phone"))
    full_name = _name(first, last)
    lines = o.get("lines") or []
    return {
        "id": o.get("number") or o.get("id"),
        "status": o.get("status"),
        "email": email,
        "phone": phone,
        "customer": {
            "id": _first(cust, "id") or email,
            "email": email,
            "first_name": first,
            "last_name": last,
            "phone": phone,
        },
        "total_price": _money(o.get("grandTotal")),
        "total_discounts": _money(o.get("discountTotal")),
        "created_at": o.get("orderDate") or o.get("createdAt"),
        "note": _first(o, "comment", "internalComment"),
        "tags": "",  # Centra orders carry no Shopify-style tags
        "line_items": [{"quantity": (ln or {}).get("quantity")} for ln in lines if ln],
        "billing_address": {
            "name": _name(_first(bill, "firstName", "first_name"),
                          _first(bill, "lastName", "last_name")) or full_name,
            "company": _first(bill, "companyName", "company"),
            "address1": _first(bill, "address1", "address"),
            "address2": _first(bill, "address2", "coaddress"),
            "city": bill.get("city"),
            "country": _country(bill),
            "zip": _first(bill, "zip", "zipCode", "zipcode"),
            "phone": phone,
        },
        "shipping_address": {
            "name": _name(_first(ship, "firstName", "first_name"),
                          _first(ship, "lastName", "last_name")) or full_name,
            "address1": _first(ship, "address1", "address"),
            "address2": _first(ship, "address2", "coaddress"),
            "city": ship.get("city"),
            "country": _country(ship),
            "zip": _first(ship, "zip", "zipCode", "zipcode"),
        },
    }


def centra_orders_to_customers(orders: list[dict], today=None):
    """Centra order nodes -> one scored-ready row per customer (reuses the engine)."""
    return orders_to_customers([centra_order_to_rest(o) for o in orders], today=today)
