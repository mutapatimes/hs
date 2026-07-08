"""Open baskets: abandoned-checkout mapping, fetch pagination, and drawer payload wiring."""
import pandas as pd

from build_mvp import dashboard_payload
from scoring.combine import HIDDEN_COL, score_customers
from scoring.shopify import abandoned_to_cart, carts_by_customer
from scoring.shopify_fetch import ABANDONED_QUERY, fetch_abandoned_checkouts


def _node(cid, amount, items, created="2026-07-06T10:00:00Z", url="http://x/c"):
    return {
        "id": f"gid://shopify/AbandonedCheckout/{cid}",
        "createdAt": created,
        "abandonedCheckoutUrl": url,
        "totalPriceSet": {"shopMoney": {"amount": str(amount)}},
        "customer": {"id": f"gid://shopify/Customer/{cid}", "email": f"c{cid}@example.com"},
        "lineItems": {"nodes": [{"title": t, "quantity": q} for t, q in items]},
    }


def test_abandoned_to_cart_maps_fields():
    cart = abandoned_to_cart(_node(7, "1770.00", [("Coat", 1), ("Scarf", 1)]))
    assert cart["cid"] == "gid://shopify/Customer/7"
    assert cart["email"] == "c7@example.com"
    assert cart["value"] == 1770            # rounded int £
    assert cart["count"] == 2               # summed quantities
    assert cart["items"] == [{"title": "Coat", "qty": 1}, {"title": "Scarf", "qty": 1}]
    assert cart["started"] == "2026-07-06"  # date only
    assert cart["url"] == "http://x/c"


def test_cart_handles_missing_pieces():
    cart = abandoned_to_cart({"customer": None, "lineItems": {"nodes": []}})
    assert cart["cid"] is None and cart["value"] == 0 and cart["count"] == 0


def test_carts_by_customer_dedupes_newest_first_and_drops_empty():
    nodes = [
        _node(1, "2000", [("New", 1)], created="2026-07-07T09:00:00Z"),   # newest for cust 1
        _node(1, "500", [("Old", 1)], created="2026-07-01T09:00:00Z"),    # older, ignored
        _node(2, "0", [], created="2026-07-06T09:00:00Z"),                # empty basket -> skipped
        _node(3, "120", [("Strap", 1)]),
    ]
    by = carts_by_customer(nodes)
    assert set(by) == {"gid://shopify/Customer/1", "gid://shopify/Customer/3"}
    assert by["gid://shopify/Customer/1"]["value"] == 2000    # kept the newest, not the older £500
    assert by["gid://shopify/Customer/1"]["items"][0]["title"] == "New"


def _pageit(pages):
    """Fake transport yielding successive abandonedCheckouts pages."""
    calls = {"i": 0}

    def transport(query, variables):
        assert query == ABANDONED_QUERY
        nodes, has_next, cursor = pages[calls["i"]]
        calls["i"] += 1
        return {"data": {"abandonedCheckouts": {
            "nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}}}

    return transport, calls


def test_fetch_paginates_cursor():
    transport, calls = _pageit([
        ([_node(1, "100", [("A", 1)])], True, "cur-1"),
        ([_node(2, "200", [("B", 1)])], False, "cur-2"),
    ])
    got = fetch_abandoned_checkouts(transport)
    assert [n["customer"]["id"] for n in got] == ["gid://shopify/Customer/1", "gid://shopify/Customer/2"]
    assert calls["i"] == 2


def test_fetch_respects_max_pages():
    def transport(query, variables):            # always claims another page
        return {"data": {"abandonedCheckouts": {
            "nodes": [_node(9, "10", [("x", 1)])],
            "pageInfo": {"hasNextPage": True, "endCursor": "again"}}}}

    got = fetch_abandoned_checkouts(transport, max_pages=3)
    assert len(got) == 3


def test_dashboard_payload_attaches_cart_to_the_right_client():
    cid = "gid://shopify/Customer/555"
    df = pd.DataFrame([
        {"Name": "Jane Doe", "EMAIL_ADDR": "ceo@carlsoncapital.com", "Spent": 100,
         "CUST_ID": cid, "Count of CUST_ID": 1},
        {"Name": "Bob Smith", "EMAIL_ADDR": "bob@gmail.com", "Spent": 80,
         "CUST_ID": "gid://shopify/Customer/9", "Count of CUST_ID": 1},
    ])
    scored = score_customers(df)
    assert bool(scored[scored["CUST_ID"] == cid][HIDDEN_COL].iloc[0])   # Jane is a hidden VIC
    carts = {cid: {"cid": cid, "value": 1770, "count": 2,
                   "items": [{"title": "Coat", "qty": 1}], "started": "2026-07-06", "url": ""}}
    payload = dashboard_payload(scored, carts_by_customer=carts)
    jane = next(c for c in payload["data"] if c["cid"] == cid)
    assert jane["cart"]["value"] == 1770 and jane["cart"]["count"] == 2
    # a client without an open basket carries no cart
    others = [c for c in payload["data"] if c["cid"] != cid]
    assert all(c["cart"] is None for c in others)
