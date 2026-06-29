"""Tests for the Shopify fetch layer, using a fake in-memory transport.

No network and no credentials: a fake ``transport`` returns canned GraphQL
pages, so we can prove pagination, throttle-retry, and the full
fetch -> aggregate -> score pipeline deterministically.
"""
import pytest

from scoring.shopify_fetch import (
    ShopifyError,
    endpoint,
    fetch_orders,
    fetch_scored,
)


def _customer(cid: str, email: str, total: str):
    return {
        "id": f"gid://shopify/Customer/{cid}",
        "email": email,
        "phone": None,
        "firstName": "Test",
        "lastName": cid,
        "tags": [],
        "numberOfOrders": 1,
        "amountSpent": {"amount": total, "currencyCode": "GBP"},
        "orders": {
            "nodes": [
                {
                    "id": f"gid://shopify/Order/{cid}",
                    "createdAt": "2024-01-01T00:00:00Z",
                    "tags": [],
                    "totalPriceSet": {"shopMoney": {"amount": total}},
                    "totalDiscountsSet": {"shopMoney": {"amount": "0.00"}},
                    "billingAddress": {
                        "address1": "1 Test St", "address2": None, "city": "London",
                        "country": "United Kingdom", "countryCodeV2": "GB",
                        "zip": "SW1X 7XL", "company": None, "phone": None,
                    },
                    "shippingAddress": None,
                    "clientDetails": {"browserIp": None},
                    "lineItems": {"nodes": [{"quantity": 1}]},
                }
            ]
        },
    }


def _page(nodes, has_next, end_cursor):
    return {"data": {"customers": {
        "nodes": nodes,
        "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
    }}}


def _two_page_transport():
    """Fake Shopify: page 1 (cursor None) -> page 2 (cursor 'c1') -> stop."""
    def transport(query, variables):
        if variables.get("cursor") is None:
            return _page([_customer("1", "a@bespoke-domain.co", "100.00")], True, "c1")
        return _page([_customer("2", "b@gmail.com", "200.00")], False, None)
    return transport


def test_endpoint_normalises_shop_domain():
    assert endpoint("aubin-london", "2025-01") == (
        "https://aubin-london.myshopify.com/admin/api/2025-01/graphql.json"
    )
    assert endpoint("aubin-london.myshopify.com").endswith("/graphql.json")


def test_fetch_orders_paginates_and_adapts():
    orders = fetch_orders(_two_page_transport())
    assert len(orders) == 2                       # one order per customer, two pages
    assert {o["customer"]["id"].split("/")[-1] for o in orders} == {"1", "2"}
    assert orders[0]["billing_address"]["zip"] == "SW1X 7XL"   # REST shape


def test_max_pages_caps_the_pull():
    orders = fetch_orders(_two_page_transport(), max_pages=1)
    assert len(orders) == 1                        # stopped after the first page


def test_fetch_scored_runs_the_full_pipeline():
    scored = fetch_scored(_two_page_transport())
    assert len(scored) == 2
    # Customer 1 ships to SW1X (HNWI postcode) -> a signal must have fired.
    assert scored["signal_count"].sum() >= 1
    assert "hidden_vic" in scored.columns


def test_non_throttle_errors_raise():
    def transport(query, variables):
        return {"errors": [{"message": "Bad scope", "extensions": {"code": "ACCESS_DENIED"}}]}
    with pytest.raises(ShopifyError):
        fetch_orders(transport)


def test_throttling_is_retried_then_succeeds():
    calls = {"n": 0}

    def transport(query, variables):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]}
        return _page([_customer("9", "x@gmail.com", "50.00")], False, None)

    # Inject a no-op sleep so the retry doesn't actually wait.
    from scoring import shopify_fetch
    orders = shopify_fetch.fetch_orders(
        transport, retries=3, _sleep=lambda _s: None
    )
    assert len(orders) == 1 and calls["n"] == 2
