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
