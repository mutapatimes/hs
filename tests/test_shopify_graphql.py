"""Tests for the GraphQL->REST adapter, using the real GraphQL Admin shape."""
from scoring.combine import score_customers
from scoring.shopify import orders_to_customers
from scoring.shopify_graphql import (
    graphql_customers_to_orders,
    order_node_to_rest,
)

# One customer node as the GraphQL Admin API returns it (trimmed).
SAMPLE_CUSTOMER = {
    "id": "gid://shopify/Customer/207119551",
    "email": "bob.norman@mail.example.com",
    "phone": "+13125551212",
    "firstName": "Bob",
    "lastName": "Norman",
    "tags": ["loyal", "vip"],
    "numberOfOrders": 2,
    "amountSpent": {"amount": "509.94", "currencyCode": "GBP"},
    "orders": {
        "nodes": [
            {
                "id": "gid://shopify/Order/1001",
                "createdAt": "2007-01-01T00:00:00Z",
                "tags": [],
                "totalPriceSet": {"shopMoney": {"amount": "100.00"}},
                "totalDiscountsSet": {"shopMoney": {"amount": "0.00"}},
                "billingAddress": {
                    "address1": "1 Old Rd", "address2": None, "city": "Leeds",
                    "country": "United Kingdom", "countryCodeV2": "GB",
                    "zip": "LS1 1AA", "company": None, "phone": None,
                },
                "shippingAddress": {
                    "address1": "1 Old Rd", "address2": None, "city": "Leeds",
                    "country": "United Kingdom", "countryCodeV2": "GB",
                    "zip": "LS1 1AA", "company": None, "phone": None,
                },
                "clientDetails": {"browserIp": "10.0.0.1"},
                "lineItems": {"nodes": [{"quantity": 1}]},
            },
            {
                "id": "gid://shopify/Order/1002",
                "createdAt": "2008-01-10T11:00:00Z",
                "tags": ["imported"],
                "totalPriceSet": {"shopMoney": {"amount": "409.94"}},
                "totalDiscountsSet": {"shopMoney": {"amount": "0.00"}},
                "billingAddress": {
                    "address1": "2259 Park Ct", "address2": "Apartment 5",
                    "city": "Drayton Valley", "country": "Canada",
                    "countryCodeV2": "CA", "zip": "T0E 0M0", "company": None,
                    "phone": "(555)555-5555",
                },
                "shippingAddress": {
                    "address1": "123 Amoebobacterieae St", "address2": "",
                    "city": "Ottawa", "country": "Canada", "countryCodeV2": "CA",
                    "zip": "K2P0V6", "company": None, "phone": None,
                },
                "clientDetails": {"browserIp": "216.191.105.146"},
                "lineItems": {"nodes": [{"quantity": 1}, {"quantity": 2}]},
            },
        ]
    },
}


def test_order_node_maps_to_rest_shape():
    order = SAMPLE_CUSTOMER["orders"]["nodes"][1]
    rest = order_node_to_rest(order, SAMPLE_CUSTOMER)

    # Shape matches what flatten_order reads.
    assert rest["total_price"] == "409.94"
    assert rest["created_at"] == "2008-01-10T11:00:00Z"
    assert rest["billing_address"]["zip"] == "T0E 0M0"
    assert rest["billing_address"]["country"] == "Canada"        # NAME, not code
    assert rest["billing_address"]["country_code"] == "CA"        # carried along
    assert rest["shipping_address"]["city"] == "Ottawa"
    # Shopify removed Order.clientDetails (browser IP) in recent API versions — no longer mapped.
    assert "client_details" not in rest
    assert [li["quantity"] for li in rest["line_items"]] == [1, 2]
    # GraphQL list tags flattened to the comma string flatten_order splits on.
    assert rest["customer"]["tags"] == "loyal, vip"
    assert rest["customer"]["amount_spent"] == "509.94"          # stashed for §5a
    assert rest["customer"]["number_of_orders"] == 2


def test_product_search_node_extracts_numeric_variant_ids():
    from scoring.shopify_graphql import product_search_node
    node = {"id": "gid://shopify/Product/9", "title": "Silk Scarf",
            "featuredImage": {"url": "http://img"},
            "variants": {"nodes": [
                {"id": "gid://shopify/ProductVariant/111", "title": "Blue", "price": "120.00",
                 "availableForSale": True},
                {"id": "gid://shopify/ProductVariant/222", "title": "Red", "price": "120.00",
                 "availableForSale": False}]}}
    p = product_search_node(node)
    assert p["id"] == "9" and p["title"] == "Silk Scarf" and p["image"] == "http://img"
    assert [v["id"] for v in p["variants"]] == ["111"]        # unavailable variant dropped
    assert p["variants"][0]["price"] == "120.00"


def test_order_maps_utm_campaign_from_journey():
    order = dict(SAMPLE_CUSTOMER["orders"]["nodes"][1])
    order["customerJourneySummary"] = {"lastVisit": {"utmParameters": {"campaign": "spring-preview"}}}
    assert order_node_to_rest(order, SAMPLE_CUSTOMER)["utm_campaign"] == "spring-preview"


def test_order_utm_campaign_is_none_without_journey():
    order = SAMPLE_CUSTOMER["orders"]["nodes"][1]
    assert order_node_to_rest(order, SAMPLE_CUSTOMER)["utm_campaign"] is None


def test_adapter_feeds_the_untouched_core():
    orders = graphql_customers_to_orders([SAMPLE_CUSTOMER])
    assert len(orders) == 2                       # two orders, one customer

    cust = orders_to_customers(orders)
    assert len(cust) == 1                         # aggregated to one row
    assert cust.iloc[0]["Spent"] == 509.94        # 100 + 409.94
    assert cust.iloc[0]["Items"] == 4             # 1 + (1+2)
    # LATEST_* taken from the most recent (2008) order.
    assert cust.iloc[0]["LATEST_BILLING_ADDRESS3"] == "Drayton Valley"
    assert cust.iloc[0]["SEGMENT"] == "VIP"       # 'vip' tag unions through

    scored = score_customers(cust)                # must run; all signal cols exist
    assert "signal_score" in scored.columns


def test_customer_with_no_orders_is_skipped():
    empty = {**SAMPLE_CUSTOMER, "orders": {"nodes": []}}
    assert graphql_customers_to_orders([empty]) == []


# ── marketing consent, read back so a burst can show it per client ──────────────────
def test_customer_node_requests_both_consent_fields():
    from scoring.shopify_graphql import _CUSTOMER_NODE, _CUSTOMER_NODE_JOURNEY
    for node in (_CUSTOMER_NODE, _CUSTOMER_NODE_JOURNEY):
        assert "emailMarketingConsent { marketingState }" in node
        assert "smsMarketingConsent { marketingState }" in node


def test_consent_state_maps_every_shopify_state_to_three_words():
    from scoring.shopify_graphql import _consent_state
    assert _consent_state({"marketingState": "SUBSCRIBED"}) == "subscribed"
    for st in ("UNSUBSCRIBED", "NOT_SUBSCRIBED", "PENDING", "INVALID", "REDACTED"):
        assert _consent_state({"marketingState": st}) == "not_subscribed", st
    assert _consent_state(None) == "unknown" and _consent_state({}) == "unknown"


def test_order_node_carries_consent_and_older_shapes_read_unknown():
    cust = {**SAMPLE_CUSTOMER,
            "emailMarketingConsent": {"marketingState": "SUBSCRIBED"},
            "smsMarketingConsent": {"marketingState": "NOT_SUBSCRIBED"}}
    rest = order_node_to_rest(SAMPLE_CUSTOMER["orders"]["nodes"][0], cust)
    assert rest["customer"]["consent"] == {"email": "subscribed", "sms": "not_subscribed"}
    old = order_node_to_rest(SAMPLE_CUSTOMER["orders"]["nodes"][0], SAMPLE_CUSTOMER)
    assert old["customer"]["consent"] == {"email": "unknown", "sms": "unknown"}


def test_data_consent_side_map_is_keyed_by_customer_and_empty_for_rest_shapes():
    from halia.api.data import _consent
    shopify = [{"customer": {"id": "gid://shopify/Customer/1",
                             "consent": {"email": "subscribed", "sms": "unknown"}}},
               {"customer": {"id": "gid://shopify/Customer/1",
                             "consent": {"email": "not_subscribed", "sms": "unknown"}}}]   # first wins
    assert _consent(shopify) == {"gid://shopify/Customer/1": {"email": "subscribed", "sms": "unknown"}}
    woo = [{"customer": {"id": 5, "email": "a@b.com"}}]      # WooCommerce carries no consent
    assert _consent(woo) == {}


def test_sale_date_is_processed_at_when_shopify_has_it():
    """An order imported when a brand moved to Shopify (or seeded into a development store) is
    created on the import day; processedAt is the day of the sale, and that is what Last Shopped,
    gone-quiet and the campaign windows must read. Without it, createdAt stands in."""
    order = dict(SAMPLE_CUSTOMER["orders"]["nodes"][1], processedAt="2007-03-05T09:00:00Z")
    rest = order_node_to_rest(order, SAMPLE_CUSTOMER)
    assert rest["created_at"] == "2007-03-05T09:00:00Z"
    assert rest["processed_at"] == "2007-03-05T09:00:00Z" and rest["imported_at"] == "2008-01-10T11:00:00Z"
    rows = orders_to_customers([rest])
    assert str(rows.iloc[0]["Last Shopped"]).startswith("2007-03-05")
    plain = order_node_to_rest(SAMPLE_CUSTOMER["orders"]["nodes"][1], SAMPLE_CUSTOMER)
    assert plain["created_at"] == "2008-01-10T11:00:00Z" and plain["processed_at"] is None
