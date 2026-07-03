"""BigCommerce adapter: order mapping, customer aggregation, paged fetch, scoring."""
from scoring.bigcommerce import bigcommerce_orders_to_customers, bigcommerce_to_rest
from scoring.bigcommerce_fetch import endpoint, fetch_orders
from scoring.combine import score_customers

# Two orders from the same customer + one from another (BigCommerce v2 /orders shape:
# street_1/zip/country_iso2, items_total instead of a line-items array, RFC-2822 dates).
ORDERS = [
    {
        "id": 101, "customer_id": 7, "email": "amara@blackstone.com", "status": "Shipped",
        "items_total": 3, "total_inc_tax": "1200.00", "discount_amount": "0.00",
        "date_created": "Tue, 27 Feb 2026 10:00:00 +0000",
        "billing_address": {"first_name": "Amara", "last_name": "Okafor", "company": "Blackstone",
                            "phone": "+447700900111", "street_1": "1 Mayfair", "city": "London",
                            "zip": "W1K 1AA", "country_iso2": "GB", "email": "amara@blackstone.com"},
    },
    {
        "id": 102, "customer_id": 7, "email": "amara@blackstone.com", "status": "Shipped",
        "items_total": 1, "total_inc_tax": "800.00",
        "date_created": "Sun, 15 Mar 2026 10:00:00 +0000",
        "billing_address": {"first_name": "Amara", "last_name": "Okafor", "street_1": "1 Mayfair",
                            "city": "London", "zip": "W1K 1AA", "country_iso2": "GB",
                            "email": "amara@blackstone.com"},
    },
    {
        "id": 103, "customer_id": 0, "email": "bob@gmail.com", "status": "Shipped",
        "items_total": 1, "total_inc_tax": "60.00", "date_created": "Fri, 10 Jan 2026 10:00:00 +0000",
        "billing_address": {"first_name": "Bob", "last_name": "Smith", "street_1": "2 High St",
                            "city": "Hull", "zip": "HU1 1AA", "country_iso2": "GB",
                            "email": "bob@gmail.com"},
    },
]


def test_order_mapping_to_engine_shape():
    rest = bigcommerce_to_rest(ORDERS[0])
    assert rest["customer"]["email"] == "amara@blackstone.com"
    assert rest["billing_address"]["zip"] == "W1K 1AA"          # BC 'zip' -> engine 'zip'
    assert rest["billing_address"]["country"] == "GB"           # country_iso2 -> ISO
    assert rest["billing_address"]["name"] == "Amara Okafor"
    assert rest["total_price"] == "1200.00"                     # total_inc_tax
    assert sum(li["quantity"] for li in rest["line_items"]) == 3  # from items_total
    assert rest["created_at"][:10] == "2026-02-27"             # RFC-2822 -> ISO


def test_aggregates_one_row_per_customer():
    df = bigcommerce_orders_to_customers(ORDERS)
    assert len(df) == 2
    amara = df[df["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    assert amara["Spent"] == 2000.0            # 1200 + 800
    assert amara["orders_count"] == 2
    assert amara["LATEST_BILLING_ZIP"] == "W1K 1AA"


def test_scores_through_unchanged_engine():
    df = bigcommerce_orders_to_customers(ORDERS).rename(columns={"orders_count": "Count of CUST_ID"})
    scored = score_customers(df)
    amara = scored[scored["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    assert "Work email" in amara["reasons"]    # the Blackstone domain fires the work-email signal


def test_endpoint_and_paged_fetch():
    assert endpoint("abc12def") == "https://api.bigcommerce.com/stores/abc12def/v2/orders"

    calls = []

    def transport(path, params):           # v2 returns a bare array; [] ends pagination (204)
        calls.append((path, params["page"]))
        return ORDERS if params["page"] == 1 else []

    got = fetch_orders(transport, per_page=250)
    assert len(got) == 3 and calls[0] == ("orders", 1)


def test_fetch_unwraps_v3_data_envelope_and_caps_pages():
    seen = []

    def transport(path, params):           # a {"data": [...]} envelope, always full -> would page forever
        seen.append(params["page"])
        return {"data": [{"id": 1}] * params["limit"]}

    got = fetch_orders(transport, per_page=250, max_pages=3)
    assert len(seen) == 3 and len(got) == 750   # max_pages bounds the pull; envelope unwrapped
