"""Map WooCommerce REST order JSON into the engine's per-customer schema.

WooCommerce `/wc/v3/orders` objects are close to Shopify's REST order shape, so we
re-map each order into the dict that ``scoring.shopify.flatten_order`` already reads
and reuse ``orders_to_customers``. The scoring engine itself stays identical across
data sources — only this thin mapping layer is source-specific.
"""
from __future__ import annotations

from scoring.shopify import orders_to_customers


def _name(*parts) -> str:
    return " ".join(p for p in parts if p).strip()


def woo_order_to_rest(o: dict) -> dict:
    """Map one WooCommerce order to the Shopify-REST shape flatten_order expects."""
    bill = o.get("billing") or {}
    ship = o.get("shipping") or {}
    email = bill.get("email") or o.get("billing_email")
    full_name = _name(bill.get("first_name"), bill.get("last_name"))
    return {
        "id": o.get("id"),
        "status": o.get("status"),  # woo: pending/processing/on-hold/completed/cancelled/refunded
        "email": email,
        "phone": bill.get("phone"),
        "customer": {
            "id": o.get("customer_id") or email,
            "email": email,
            "first_name": bill.get("first_name"),
            "last_name": bill.get("last_name"),
            "phone": bill.get("phone"),
        },
        "total_price": o.get("total"),
        "total_discounts": o.get("discount_total"),
        "created_at": o.get("date_created_gmt") or o.get("date_created"),
        "note": o.get("customer_note"),  # woo: the shopper's order note
        "tags": "",  # WooCommerce orders have no native tags
        "line_items": [{"quantity": li.get("quantity")} for li in (o.get("line_items") or [])],
        "billing_address": {
            "name": full_name,
            "company": bill.get("company"),
            "address1": bill.get("address_1"),
            "address2": bill.get("address_2"),
            "city": bill.get("city"),
            "country": bill.get("country"),
            "zip": bill.get("postcode"),
            "phone": bill.get("phone"),
        },
        "shipping_address": {
            "name": _name(ship.get("first_name"), ship.get("last_name")) or full_name,
            "address1": ship.get("address_1"),
            "address2": ship.get("address_2"),
            "city": ship.get("city"),
            "country": ship.get("country"),
            "zip": ship.get("postcode"),
        },
    }


def woo_orders_to_customers(orders: list[dict], today=None):
    """WooCommerce orders -> one scored-ready row per customer (reuses the engine)."""
    return orders_to_customers([woo_order_to_rest(o) for o in orders], today=today)
