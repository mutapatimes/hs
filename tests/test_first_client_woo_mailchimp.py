"""End-to-end guard for the first client: WooCommerce orders -> engine -> Mailchimp upsert.

This is the exact production path the hosted app runs for a WooCommerce + Mailchimp tenant
(scoring/woocommerce -> scoring.combine -> halia.engine -> halia.adapters.mailchimp_sink),
exercised in memory with a fake Mailchimp transport so it never touches the network. If a change
breaks the path our first real client depends on, this test fails.

The two ends differ from the Shopify/Klaviyo demo; the engine in the middle is unchanged.
"""
from halia.adapters.mailchimp_sink import MailchimpSink, subscriber_hash
from halia.engine import engine
from scoring.woocommerce import woo_orders_to_customers

# A prime hidden VIC (work email + Mayfair) and a plain shopper, in the WooCommerce orders shape.
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

AMARA, BOB = "amara@blackstone.com", "bob@gmail.com"


class FakeMailchimp:
    """Records every (method, path, body); answers as Mailchimp would for the happy path."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and "merge-fields" in path:
            return 200, {"merge_fields": []}          # none yet -> sink will create them
        return 200, {"id": "stub"}

    def puts(self):
        return [(p, b) for (m, p, b) in self.calls if m == "PUT"]


def _surfaced_results():
    """woo orders -> aggregated customers -> scored -> ScoreResult list -> the flagged ones,
    mirroring halia.api.data.hidden_results / the /v1/mailchimp/push endpoint's selection."""
    df = woo_orders_to_customers(ORDERS).rename(columns={"orders_count": "Count of CUST_ID"})
    results = engine.results_from_scored(engine.score_frame(df))
    return [r for r in results if r.flagged]


def test_woo_to_mailchimp_upserts_only_the_surfaced_vic():
    surfaced = _surfaced_results()
    emails = {r.email for r in surfaced}
    assert AMARA in emails                      # the work-email/Mayfair client is surfaced
    assert BOB not in emails                    # the plain gmail shopper is not flagged

    fake = FakeMailchimp()
    sink = MailchimpSink("key-us21", "list123", transport=fake)
    sink.ensure_merge_fields()
    pushed = sink.push_many(surfaced)

    # Exactly the surfaced client(s) upserted, addressed by Mailchimp's md5-of-email subscriber id.
    assert pushed == len(surfaced) >= 1
    put_paths = [p for (p, _b) in fake.puts()]
    assert f"/lists/list123/members/{subscriber_hash(AMARA)}" in put_paths
    assert subscriber_hash(BOB) not in " ".join(put_paths)


def test_upsert_carries_halia_grade_reasons_and_tags():
    amara = next(r for r in _surfaced_results() if r.email == AMARA)
    fake = FakeMailchimp()
    MailchimpSink("key-us21", "list123", transport=fake).push_one(amara)

    # The member PUT writes Halia's verdict into merge fields the client can segment on.
    put = next(b for (m, p, b) in fake.calls if m == "PUT")
    mf = put["merge_fields"]
    assert mf["HGRADE"] == amara.grade and mf["HGRADE"]
    assert "Work email" in mf["HREASONS"]
    assert mf["HVIC"] in ("Yes", "No")

    # And at least one "Halia …" tag is applied for use as a Mailchimp segment/automation trigger.
    tag_posts = [b for (m, p, b) in fake.calls if m == "POST" and p.endswith("/tags")]
    assert tag_posts and any(t["name"].startswith("Halia") for t in tag_posts[0]["tags"])


def test_merge_fields_are_provisioned_on_a_fresh_audience():
    fake = FakeMailchimp()
    MailchimpSink("key-us21", "list123", transport=fake).ensure_merge_fields()
    created = {b["tag"] for (m, p, b) in fake.calls if m == "POST" and p.endswith("/merge-fields")}
    assert {"HGRADE", "HSCORE", "HVIC"} <= created      # Halia fields exist before any push
