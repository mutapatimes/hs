"""Centra adapter: order mapping, customer aggregation, cursor fetch, scoring."""
import pytest

from scoring.centra import centra_order_to_rest, centra_orders_to_customers
from scoring.centra_fetch import ORDER_QUERY, CentraAuthError, endpoint, fetch_orders
from scoring.combine import score_customers

# Two orders from the same customer + one from another, in the Centra GraphQL
# Integration API node shape: grandTotal{value}, country{code}, orderDate ISO,
# lines with quantities, camelCase address fields.
ORDERS = [
    {
        "number": 1101, "status": "SHIPPED", "orderDate": "2026-02-27T10:00:00+00:00",
        "grandTotal": {"value": 1200.0},
        "customer": {"email": "amara@blackstone.com", "firstName": "Amara", "lastName": "Okafor"},
        "billingAddress": {"firstName": "Amara", "lastName": "Okafor", "companyName": "Blackstone",
                           "address1": "1 Mayfair", "city": "London", "zip": "W1K 1AA",
                           "country": {"code": "GB"}, "phoneNumber": "+447700900111",
                           "email": "amara@blackstone.com"},
        "shippingAddress": {"firstName": "Amara", "lastName": "Okafor", "address1": "1 Mayfair",
                            "city": "London", "zip": "W1K 1AA", "country": {"code": "GB"}},
        "lines": [{"quantity": 2}, {"quantity": 1}],
    },
    {
        "number": 1102, "status": "SHIPPED", "orderDate": "2026-03-15T10:00:00+00:00",
        "grandTotal": {"value": 800.0},
        "customer": {"email": "amara@blackstone.com", "firstName": "Amara", "lastName": "Okafor"},
        "billingAddress": {"firstName": "Amara", "lastName": "Okafor", "address1": "1 Mayfair",
                           "city": "London", "zip": "W1K 1AA", "country": {"code": "GB"}},
        "shippingAddress": {},
        "lines": [{"quantity": 1}],
    },
    {
        "number": 1103, "status": "SHIPPED", "orderDate": "2026-01-10T10:00:00+00:00",
        "grandTotal": {"value": 60.0},
        "customer": {"email": "bob@gmail.com", "firstName": "Bob", "lastName": "Smith"},
        "billingAddress": {"firstName": "Bob", "lastName": "Smith", "address1": "2 High St",
                           "city": "Hull", "zipCode": "HU1 1AA", "country": {"code": "GB"}},
        "shippingAddress": {},
        "lines": [{"quantity": 1}],
    },
]


def test_order_mapping_to_engine_shape():
    rest = centra_order_to_rest(ORDERS[0])
    assert rest["id"] == 1101                                    # number -> id
    assert rest["customer"]["email"] == "amara@blackstone.com"
    assert rest["billing_address"]["zip"] == "W1K 1AA"
    assert rest["billing_address"]["country"] == "GB"            # country{code} -> ISO
    assert rest["billing_address"]["name"] == "Amara Okafor"
    assert rest["billing_address"]["company"] == "Blackstone"    # companyName -> company
    assert rest["phone"] == "+447700900111"                      # phoneNumber -> phone
    assert rest["total_price"] == 1200.0                         # grandTotal.value
    assert sum(li["quantity"] for li in rest["line_items"]) == 3
    assert rest["created_at"][:10] == "2026-02-27"


def test_mapping_tolerates_schema_spelling_variants():
    # zipCode instead of zip must still land in the engine's 'zip' slot.
    rest = centra_order_to_rest(ORDERS[2])
    assert rest["billing_address"]["zip"] == "HU1 1AA"


def test_aggregates_one_row_per_customer():
    df = centra_orders_to_customers(ORDERS)
    assert len(df) == 2
    amara = df[df["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    assert amara["Spent"] == 2000.0            # 1200 + 800
    assert amara["orders_count"] == 2
    assert amara["LATEST_BILLING_ZIP"] == "W1K 1AA"


def test_scores_through_unchanged_engine():
    df = centra_orders_to_customers(ORDERS).rename(columns={"orders_count": "Count of CUST_ID"})
    scored = score_customers(df)
    amara = scored[scored["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    assert "Work email" in amara["reasons"]    # the Blackstone domain fires the work-email signal


def _page(nodes, has_next, cursor):
    return {"orderConnection": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        "edges": [{"node": n} for n in nodes],
    }}


def test_endpoint_and_cursor_fetch():
    assert endpoint("https://yourbrand.centra.com/") == "https://yourbrand.centra.com/graphql"

    calls = []

    def transport(query, variables):
        calls.append(variables.get("after"))
        assert query == ORDER_QUERY
        if variables.get("after") is None:
            return _page(ORDERS[:2], True, "cursor-1")
        return _page(ORDERS[2:], False, "cursor-2")

    got = fetch_orders(transport, page_size=2)
    assert [o["number"] for o in got] == [1101, 1102, 1103]
    assert calls == [None, "cursor-1"]          # second page requested with the cursor


def test_fetch_caps_pages():
    def transport(query, variables):            # always claims another page -> would loop forever
        return _page([{"number": 1}], True, "again")

    got = fetch_orders(transport, page_size=1, max_pages=3)
    assert len(got) == 3


def test_auth_error_type_exists():
    with pytest.raises(CentraAuthError):
        raise CentraAuthError("token rejected")
