"""WooCommerce adapter: order mapping, customer aggregation, paged fetch, scoring."""
from scoring.combine import score_customers
from scoring.woocommerce import woo_order_to_rest, woo_orders_to_customers
from scoring.woocommerce_fetch import endpoint, fetch_orders

# Two orders from the same customer + one from another (WooCommerce /wc/v3/orders shape).
ORDERS = [
    {
        "id": 101, "customer_id": 7, "total": "1200.00", "discount_total": "0.00",
        "date_created_gmt": "2026-02-01T10:00:00",
        "billing": {"first_name": "Amara", "last_name": "Okafor", "email": "amara@blackstone.com",
                    "phone": "+447700900111", "company": "Blackstone",
                    "address_1": "1 Mayfair", "city": "London", "postcode": "W1K 1AA", "country": "GB"},
        "shipping": {"first_name": "Amara", "last_name": "Okafor", "address_1": "1 Mayfair",
                     "city": "London", "postcode": "W1K 1AA", "country": "GB"},
        "line_items": [{"quantity": 2}, {"quantity": 1}],
    },
    {
        "id": 102, "customer_id": 7, "total": "800.00", "discount_total": "0.00",
        "date_created_gmt": "2026-03-15T10:00:00",
        "billing": {"first_name": "Amara", "last_name": "Okafor", "email": "amara@blackstone.com",
                    "phone": "+447700900111", "address_1": "1 Mayfair", "city": "London",
                    "postcode": "W1K 1AA", "country": "GB"},
        "shipping": {}, "line_items": [{"quantity": 1}],
    },
    {
        "id": 103, "customer_id": 0, "total": "60.00", "discount_total": "0.00",
        "date_created_gmt": "2026-01-10T10:00:00",
        "billing": {"first_name": "Bob", "last_name": "Smith", "email": "bob@gmail.com",
                    "address_1": "2 High St", "city": "Hull", "postcode": "HU1 1AA", "country": "GB"},
        "shipping": {}, "line_items": [{"quantity": 1}],
    },
]


def test_order_mapping_to_engine_shape():
    rest = woo_order_to_rest(ORDERS[0])
    assert rest["customer"]["email"] == "amara@blackstone.com"
    assert rest["billing_address"]["zip"] == "W1K 1AA"
    assert rest["billing_address"]["name"] == "Amara Okafor"
    assert sum(li["quantity"] for li in rest["line_items"]) == 3


def test_aggregates_one_row_per_customer():
    df = woo_orders_to_customers(ORDERS)
    assert len(df) == 2
    amara = df[df["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    assert amara["Spent"] == 2000.0           # 1200 + 800
    assert amara["orders_count"] == 2
    assert amara["LATEST_BILLING_ZIP"] == "W1K 1AA"


def test_scores_through_unchanged_engine():
    df = woo_orders_to_customers(ORDERS).rename(columns={"orders_count": "Count of CUST_ID"})
    scored = score_customers(df)
    amara = scored[scored["EMAIL_ADDR"] == "amara@blackstone.com"].iloc[0]
    # Work-email signal should fire from the Blackstone domain.
    assert "Work email" in amara["reasons"]


def test_endpoint_and_paged_fetch():
    assert endpoint("https://shop.example.com/") == "https://shop.example.com/wp-json/wc/v3/orders"

    pages: dict[int, list] = {1: ORDERS, 2: []}
    calls = []

    def transport(path, params):
        calls.append((path, params["page"]))
        return pages.get(params["page"], [])

    got = fetch_orders(transport, per_page=100)
    assert len(got) == 3 and calls[0] == ("orders", 1)


def test_fetch_requests_only_needed_fields_and_caps_pages():
    seen = []

    def transport(path, params):
        seen.append(params)
        return [{"id": 1}] * params["per_page"]  # always full -> would page forever without a cap

    got = fetch_orders(transport, per_page=100, max_pages=3)
    # _fields trims the payload to what the scorer reads (big speed win on real stores)
    assert "_fields" in seen[0] and "billing" in seen[0]["_fields"] and "meta_data" not in seen[0]["_fields"]
    # max_pages bounds the pull so a huge store cannot run forever
    assert len(seen) == 3 and len(got) == 300
