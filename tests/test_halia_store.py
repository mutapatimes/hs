"""Secret store: encrypted token/Klaviyo roundtrip, deletion, and zero-PII schema."""
from cryptography.fernet import Fernet

from halia.store import ShopStore

SHOP = "acme.myshopify.com"


def test_token_and_klaviyo_roundtrip(tmp_path):
    s = ShopStore(db_path=tmp_path / "s.db")
    assert s.get_token(SHOP) is None and s.get_klaviyo(SHOP) is None
    s.save_shop(SHOP, "shpat_x")
    s.save_klaviyo(SHOP, "pk_abc")
    assert s.get_token(SHOP) == "shpat_x"
    assert s.get_klaviyo(SHOP) == "pk_abc"


def test_delete_shop_erases_everything(tmp_path):
    s = ShopStore(db_path=tmp_path / "s.db")
    s.save_shop(SHOP, "shpat_x")
    s.save_klaviyo(SHOP, "pk_y")
    s.delete_shop(SHOP)
    assert s.get_token(SHOP) is None and s.get_klaviyo(SHOP) is None


def test_secrets_are_encrypted_at_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("HALIA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    s = ShopStore(db_path=tmp_path / "e.db")
    s.save_shop(SHOP, "shpat_supersecret")
    raw = s._run("SELECT access_token FROM shops WHERE shop = :shop", {"shop": SHOP}, fetch="one")
    assert "shpat_supersecret" not in (raw["access_token"] or "")  # not plaintext on disk
    assert raw["access_token"].startswith("enc:v1:")
    assert s.get_token(SHOP) == "shpat_supersecret"                # decrypts on read


def test_schema_holds_no_customer_tables(tmp_path):
    """The only persisted tables are merchant secrets — never customer data."""
    s = ShopStore(db_path=tmp_path / "z.db")
    rows = s._run("SELECT name FROM sqlite_master WHERE type='table'", fetch="all")
    tables = {r["name"] for r in rows}
    assert "shops" in tables and "klaviyo" in tables
    assert {"scores", "orders", "dashboards"} & tables == set()  # purged / never created


# ── owner-dashboard activity counters ────────────────────────────────────────
def test_bump_metric_increments_within_a_week(tmp_path):
    from halia.store import _iso_week

    s = ShopStore(db_path=tmp_path / "m.db")
    wk = _iso_week()
    s.bump_metric(SHOP, "scan")
    s.bump_metric(SHOP, "scan")
    s.bump_metric(SHOP, "customers_scanned", 40)
    s.bump_metric(SHOP, "scan", 0)          # no-op, must not create noise
    s.bump_metric(SHOP, "scan", -5)         # negative, ignored
    assert s.metric_totals() == {"scan": 2, "customers_scanned": 40}
    assert s.metric_totals([wk]) == {"scan": 2, "customers_scanned": 40}
    assert s.metric_totals(["1999-W01"]) == {}   # a week with no rows


def test_metric_weekly_and_by_shop_buckets(tmp_path):
    from halia.store import recent_weeks

    s = ShopStore(db_path=tmp_path / "m.db")
    weeks = recent_weeks(3)
    s.bump_metric(SHOP, "scan", 3, week=weeks[0])
    s.bump_metric(SHOP, "scan", 5, week=weeks[2])
    s.bump_metric("bella.example.com", "scan", 1, week=weeks[2])
    assert s.metric_weekly("scan", weeks) == {weeks[0]: 3, weeks[1]: 0, weeks[2]: 6}
    by_shop = s.metric_by_shop([weeks[2]])
    assert by_shop == {SHOP: {"scan": 5}, "bella.example.com": {"scan": 1}}


def test_delete_shop_clears_metrics(tmp_path):
    s = ShopStore(db_path=tmp_path / "m.db")
    s.bump_metric(SHOP, "scan", 4)
    s.delete_shop(SHOP)
    assert s.metric_totals() == {}


def test_overview_count_helpers(tmp_path):
    s = ShopStore(db_path=tmp_path / "m.db")
    s.create_tenant(SHOP, "shopify", "Acme", "h1")
    s.create_tenant("bella.example.com", "woocommerce", "Bella", "h2")
    s.save_shop(SHOP, "shpat_x")
    s.save_klaviyo(SHOP, "pk_x")
    s.record_feedback(SHOP, ["sig_a", "sig_b"], "fit")
    s.record_feedback(SHOP, ["sig_a"], "nofit")
    assert s.count_tenants_by_kind() == {"shopify": 1, "woocommerce": 1}
    assert s.all_shops() == [SHOP]
    assert s.integrations_by_shop() == {SHOP: ["klaviyo"]}
    assert s.feedback_by_shop() == {SHOP: {"fit": 2, "nofit": 1}}
    assert s.new_tenants() == 2          # both created this week
    assert s.integration_counts()["klaviyo"]["total"] == 1
