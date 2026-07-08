"""SCAYLE adapter: order mapping, customer aggregation, cursor fetch, scoring."""
import pytest

from scoring.combine import score_customers
from scoring.scayle import scayle_order_to_rest, scayle_orders_to_customers
from scoring.scayle_fetch import ScayleAuthError, endpoint, fetch_orders

# Two orders from the same customer + one from another, in a SCAYLE Admin-API-ish shape:
# monetary amounts as integer minor units (cents) under cost.withTax, split street fields,
# camelCase addresses, ISO dates.
ORDERS = [
    {
        "id": 1101, "status": "shipped", "createdAt": "2026-02-27T10:00:00+00:00",
        "cost": {"withTax": 120000},
        "customer": {"id": 7, "email": "amara@blackstone.com", "firstName": "Amara", "lastName": "Okafor",
                     "phone": "+447700900111"},
        "billingAddress": {"firstName": "Amara", "lastName": "Okafor", "companyName": "Blackstone",
                           "street": "1 Mayfair", "houseNumber": "1", "city": "London",
                           "zipCode": "W1K 1AA", "countryCode": "GB"},
        "shippingAddress": {"firstName": "Amara", "lastName": "Okafor", "street": "1 Mayfair",
                            "city": "London", "zipCode": "W1K 1AA", "countryCode": "GB"},
        "items": [{"quantity": 2}, {"quantity": 1}],
    },
    {
        "id": 1102, "status": "shipped", "createdAt": "2026-03-15T10:00:00+00:00",
        "cost": {"withTax": 80000},
        "customer": {"id": 7, "email": "amara@blackstone.com", "firstName": "Amara", "lastName": "Okafor"},
        "billingAddress": {"street": "1 Mayfair", "city": "London", "zipCode": "W1K 1AA", "countryCode": "GB"},
        "items": [{"quantity": 1}],
    },
    {
        # variant spellings: orderNumber instead of id, lineItems, postalCode, phoneNumber
        "orderNumber": 1103, "status": "shipped", "orderedAt": "2026-01-10T10:00:00+00:00",
        "total": {"amount": 6000},
        "customer": {"id": 9, "email": "bob@gmail.com", "firstName": "Bob", "lastName": "Smith",
                     "phoneNumber": "+447700900222"},
        "billingAddress": {"address1": "2 High St", "city": "Hull", "postalCode": "HU1 1AA",
                           "country": {"code": "GB"}},
        "lineItems": [{"quantity": 1}],
    },
]


def test_order_mapping_to_engine_shape():
    rest = scayle_order_to_rest(ORDERS[0])
    assert rest["id"] == 1101
    assert rest["customer"]["email"] == "amara@blackstone.com"
    assert rest["billing_address"]["zip"] == "W1K 1AA"
    assert rest["billing_address"]["country"] == "GB"
    assert rest["billing_address"]["company"] == "Blackstone"
    assert rest["billing_address"]["address1"].startswith("1 Mayfair")
    assert rest["phone"] == "+447700900111"
    assert rest["total_price"] == 1200.0                # cost.withTax 120000 cents -> £1200
    assert sum(li["quantity"] for li in rest["line_items"]) == 3
    assert rest["created_at"][:10] == "2026-02-27"


def test_mapping_tolerates_field_variants():
    rest = scayle_order_to_rest(ORDERS[2])
    assert rest["id"] == 1103                           # orderNumber -> id
    assert rest["billing_address"]["zip"] == "HU1 1AA"  # postalCode -> zip
    assert rest["billing_address"]["country"] == "GB"   # country{code} -> ISO
    assert rest["phone"] == "+447700900222"             # phoneNumber -> phone
    assert rest["total_price"] == 60.0                  # total.amount 6000 cents -> £60
    assert rest["created_at"][:10] == "2026-01-10"      # orderedAt -> created_at


def test_aggregates_one_row_per_customer():
    df = scayle_orders_to_customers(ORDERS)
    assert len(df) == 2
    amara = df[df["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    assert amara["Spent"] == 2000.0                     # 1200 + 800
    assert amara["orders_count"] == 2
    assert amara["LATEST_BILLING_ZIP"] == "W1K 1AA"


def test_scores_through_unchanged_engine():
    df = scayle_orders_to_customers(ORDERS).rename(columns={"orders_count": "Count of CUST_ID"})
    scored = score_customers(df)
    amara = scored[scored["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    assert "Work email" in amara["reasons"]             # the Blackstone domain fires work-email


def test_endpoint_and_cursor_fetch():
    assert endpoint("https://brand.scayle.cloud/", "orders") == \
        "https://brand.scayle.cloud/api/admin/v1/orders"

    calls = []

    def transport(path, params):
        assert path == "orders"
        calls.append(params.get("cursor"))
        if not params.get("cursor"):
            return {"data": ORDERS[:2], "cursor": {"next": "cursor-1"}}
        return {"data": ORDERS[2:], "cursor": {"next": None}}   # no next -> stop

    got = fetch_orders(transport, page_size=2)
    assert [o.get("id") or o.get("orderNumber") for o in got] == [1101, 1102, 1103]
    assert calls == [None, "cursor-1"]                  # second page requested with the cursor


def test_fetch_caps_pages():
    def transport(path, params):                        # always claims another page
        return {"data": [{"id": 1}], "cursor": {"next": "again"}}

    got = fetch_orders(transport, page_size=1, max_pages=3)
    assert len(got) == 3


def test_auth_error_type_exists():
    with pytest.raises(ScayleAuthError):
        raise ScayleAuthError("token rejected")
