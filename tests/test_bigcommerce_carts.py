"""BigCommerce open baskets: incomplete-order (status_id 0) mapping + product enrichment."""
from scoring.bigcommerce import carts_by_customer, incomplete_to_cart, products_to_items
from scoring.bigcommerce_fetch import fetch_order_products


def _incomplete(cid, total, items_total, created="Mon, 06 Jul 2026 10:00:00 +0000", email=None):
    o = {"id": 900 + (cid or 0), "customer_id": cid, "total_inc_tax": str(total),
         "items_total": items_total, "date_created": created}
    if email:
        o["email"] = email
    return o


def test_incomplete_to_cart_maps_fields():
    cart = incomplete_to_cart(_incomplete(7, "1770.00", 2))
    assert cart["cid"] == "7"                 # keyed by customer_id (matches CUST_ID)
    assert cart["value"] == 1770 and cart["count"] == 2
    assert cart["started"] == "2026-07-06"    # RFC-2822 -> ISO date
    assert cart["items"] == [] and cart["url"] == ""
    assert cart["order_id"] == 907


def test_guest_cart_keys_by_email():
    cart = incomplete_to_cart(_incomplete(0, "300", 1, email="guest@example.com"))
    assert cart["cid"] == "guest@example.com"  # customer_id 0 (guest) -> email, mirrors the scorer


def test_products_to_items():
    items = products_to_items([{"name": "Coat", "quantity": 1}, {"name": "Scarf", "quantity": "2"}])
    assert items == [{"title": "Coat", "qty": 1}, {"title": "Scarf", "qty": 2}]


def test_carts_by_customer_dedupes_newest_first_and_drops_empty():
    orders = [
        _incomplete(1, "2000", 1, created="Tue, 07 Jul 2026 09:00:00 +0000"),  # newest for cust 1
        _incomplete(1, "500", 1, created="Wed, 01 Jul 2026 09:00:00 +0000"),   # older -> ignored
        _incomplete(2, "0", 0),                                                # empty -> skipped
        _incomplete(3, "120", 1),
    ]
    by = carts_by_customer(orders)
    assert set(by) == {"1", "3"}
    assert by["1"]["value"] == 2000           # kept the newest, not the older £500


def test_fetch_order_products_paginates():
    pages = {1: [{"name": "A", "quantity": 1}], 2: []}

    def transport(path, params):
        assert path == "orders/907/products"
        return pages.get(params["page"], [])

    # a single short page ends the loop
    got = fetch_order_products(transport, 907, per_page=250)
    assert got == [{"name": "A", "quantity": 1}]
