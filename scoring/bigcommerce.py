"""Map BigCommerce REST order JSON into the engine's per-customer schema.

BigCommerce v2 `/orders` objects differ from Shopify's REST shape: addresses use
`street_1`/`street_2`/`zip`/`country_iso2`, totals are `total_inc_tax`, there is no inline
line-items array (we use `items_total` for the quantity), and dates are RFC-2822. We re-map each
order into the dict ``scoring.shopify.flatten_order`` already reads and reuse
``orders_to_customers`` — the scoring engine itself stays identical across data sources.
"""
from __future__ import annotations

from scoring.shopify import orders_to_customers


def _name(*parts) -> str:
    return " ".join(p for p in parts if p).strip()


def _iso(dt: str) -> str:
    """BigCommerce v2 dates are RFC-2822 ('Tue, 27 Feb 2026 10:00:00 +0000'); the scorer only
    needs the leading YYYY-MM-DD, so normalise to ISO where we can (pass through on failure)."""
    if not dt:
        return dt
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(dt).isoformat()
    except (TypeError, ValueError):
        return dt


def bigcommerce_to_rest(o: dict) -> dict:
    """Map one BigCommerce order to the Shopify-REST shape flatten_order expects."""
    bill = o.get("billing_address") or {}
    ship = o.get("shipping_address") or {}
    if isinstance(ship, list):                 # BigCommerce can nest multiple shipping addresses
        ship = ship[0] if ship else {}
    if not isinstance(ship, dict):             # or a resource reference (a URL) — ignore it
        ship = {}
    email = o.get("email") or bill.get("email")
    full_name = _name(bill.get("first_name"), bill.get("last_name"))
    items = o.get("items_total")
    return {
        "id": o.get("id"),
        "status": o.get("status"),  # e.g. "Awaiting Fulfillment", "Shipped", "Cancelled"
        "email": email,
        "phone": bill.get("phone"),
        "customer": {
            "id": o.get("customer_id") or email,
            "email": email,
            "first_name": bill.get("first_name"),
            "last_name": bill.get("last_name"),
            "phone": bill.get("phone"),
        },
        "total_price": o.get("total_inc_tax") or o.get("total_ex_tax"),
        "total_discounts": o.get("discount_amount"),
        "created_at": _iso(o.get("date_created")),
        "note": o.get("customer_message"),  # bc: the shopper's order comment
        "tags": "",  # BigCommerce orders have no native tags
        "line_items": [{"quantity": items}] if items else [],
        "billing_address": {
            "name": full_name,
            "company": bill.get("company"),
            "address1": bill.get("street_1"),
            "address2": bill.get("street_2"),
            "city": bill.get("city"),
            "country": bill.get("country_iso2") or bill.get("country"),
            "zip": bill.get("zip") or bill.get("postal_code"),
            "phone": bill.get("phone"),
        },
        "shipping_address": {
            "name": _name(ship.get("first_name"), ship.get("last_name")) or full_name,
            "address1": ship.get("street_1"),
            "address2": ship.get("street_2"),
            "city": ship.get("city"),
            "country": ship.get("country_iso2") or ship.get("country"),
            "zip": ship.get("zip") or ship.get("postal_code"),
        },
    }


def bigcommerce_orders_to_customers(orders: list[dict], today=None):
    """BigCommerce orders -> one scored-ready row per customer (reuses the engine)."""
    return orders_to_customers([bigcommerce_to_rest(o) for o in orders], today=today)
