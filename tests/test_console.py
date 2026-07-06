"""Console dashboard: shared-key auth (signed cookie) + aggregate metrics rendering.

No network and no real Shopify — a tmp SQLite ShopStore is injected and seeded, exactly like
the CMS test. Proves the gate (disabled without key, wrong key rejected, cookie required) and
that seeded aggregate counters/tenants surface on the page and in /console/data.json.
"""
import pytest
from fastapi.testclient import TestClient

from halia.api import console, shopify_auth
from halia.api.app import app
from halia.store import ShopStore

SHOP = "acme.myshopify.com"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "o.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr("halia.config.CONSOLE_KEY", "own3r")
    console._REV_CACHE.clear()
    yield TestClient(app), store
    console._REV_CACHE.clear()


def _login(c):
    c.post("/console/login", data={"key": "own3r"})


def _seed(store):
    store.create_tenant(SHOP, "shopify", "Acme Fashion", "h1")
    store.save_shop(SHOP, "shpat_x")
    store.save_klaviyo(SHOP, "pk_x")
    store.set_billing(SHOP, "active")
    for metric, n in [("scan", 3), ("customers_scanned", 120), ("hidden_vics", 14),
                      ("email", 9), ("action_klaviyo_push", 40), ("pos_lookup", 5)]:
        store.bump_metric(SHOP, metric, n)
    store.record_feedback(SHOP, ["hnwi_postcode", "property_area"], "fit")


# ── auth gate ────────────────────────────────────────────────────────────────
def test_disabled_without_key(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.CONSOLE_KEY", None)
    assert "HALIA_CONSOLE_KEY" in c.get("/console").text


def test_login_required_and_key_checked(client):
    c, store = client
    _seed(store)
    # Not signed in -> the login form, not the dashboard.
    assert "Sign in" in c.get("/console").text and "Console dashboard" in c.get("/console").text
    assert c.post("/console/login", data={"key": "nope"}).status_code == 401
    r = c.post("/console/login", data={"key": "own3r"}, follow_redirects=False)
    assert r.status_code == 303 and "halia_console=" in r.headers.get("set-cookie", "")


def test_data_json_requires_session(client):
    c, store = client
    _seed(store)
    assert c.get("/console/data.json").status_code == 403
    c.post("/console/login", data={"key": "own3r"})
    d = c.get("/console/data.json").json()
    assert d["clients"]["total"] == 1
    assert d["activity_week"] == {"scans": 3, "customers": 120, "hidden": 14,
                                  "emails": 9, "actions": 40, "pos": 5}


def test_logout_clears_cookie(client):
    c, _ = client
    c.post("/console/login", data={"key": "own3r"})
    r = c.get("/console/logout", follow_redirects=False)
    assert r.status_code == 303
    # After logout the protected JSON endpoint is denied again.
    c.cookies.clear()
    assert c.get("/console/data.json").status_code == 403


# ── rendering reflects seeded aggregate data ─────────────────────────────────
def test_dashboard_renders_seeded_numbers(client):
    c, store = client
    _seed(store)
    c.post("/console/login", data={"key": "own3r"})
    html = c.get("/console").text
    assert "Halia · Console" in html and "class=nav" in html   # shared shell
    assert "Acme Fashion" in html and SHOP in html      # per-tenant row
    assert "<svg" in html                                # trend sparklines
    assert "120" in html                                 # customers scanned this week


# ── multi-page: every page gated + renders ───────────────────────────────────
@pytest.mark.parametrize("path", ["/console/revenue", "/console/outreach", "/console/milestones",
                                  "/console/settings"])
def test_pages_gated_then_render(client, path):
    c, store = client
    _seed(store)
    assert "Sign in" in c.get(path).text          # not signed in -> login form
    _login(c)
    html = c.get(path).text
    assert "Halia · Console" in html and "class=nav" in html   # shared shell + nav


# ── settings persist (all four groups) ───────────────────────────────────────
def test_settings_defaults_persist_and_read_through(client):
    c, store = client
    _seed(store)
    _login(c)
    c.post("/console/settings", data={"tab": "defaults", "default_vic_threshold": "8000",
                                    "default_notify_grades": "A*,A,B", "plan_currency": "USD",
                                    "console_name": "Val", "plan_price": "299"},
           follow_redirects=False)
    from halia.console_config import console_settings
    st = console_settings()
    assert st["default_vic_threshold"] == 8000 and st["plan_currency"] == "USD"
    assert st["default_notify_grades"] == ["A*", "A", "B"]
    # read-through: a brand-new client inherits the console default threshold
    from halia.api.settings import settings_for
    assert settings_for("new.myshopify.com")["vic_threshold"] == 8000


def test_settings_access_and_revenue_and_milestones(client):
    c, store = client
    _seed(store)
    _login(c)
    # access
    c.post("/console/settings", data={"tab": "access", "signup_code": "GOLD",
                                    "free_shops": "a.myshopify.com\nb.example.com"})
    # revenue override for the seeded client
    c.post("/console/settings", data={"tab": "revenue", f"rev_{SHOP}_amount": "250",
                                    f"rev_{SHOP}_renewal": "2026-09-01", f"rev_{SHOP}_status": "active"})
    # a milestone
    c.post("/console/settings", data={"tab": "milestones", "ms_new_title": "First client",
                                    "ms_new_date": "2026-07-01", "ms_new_note": "glen norah"})
    from halia.console_config import console_settings
    st = console_settings()
    assert st["signup_code"] == "GOLD" and "a.myshopify.com" in st["free_shops"]
    assert st["revenue_overrides"][SHOP]["amount"] == 250.0
    assert st["milestones"] and st["milestones"][0]["title"] == "First client"
    # the override drives the revenue page MRR
    console._REV_CACHE.clear()
    assert console._revenue_data(force=True)["mrr"] == 250.0


def test_revenue_reads_live_stripe_subscription(client, monkeypatch):
    c, store = client
    _seed(store)  # SHOP has billing status active + a stored subscription id path
    store.set_billing(SHOP, "active", "cus_1", "sub_1")
    from halia.api import billing
    monkeypatch.setattr(billing, "billing_enabled", lambda: True)
    # Fake the subscription fetch: £49/mo, renews 2027-01-01.
    fake_sub = {"status": "active", "cancel_at_period_end": False,
                "current_period_end": 1798761600,  # 2027-01-01
                "items": {"data": [{"price": {"unit_amount": 4900, "currency": "gbp",
                                              "recurring": {"interval": "month"}}}]}}
    monkeypatch.setattr(billing, "_subscription", lambda shop: fake_sub if shop == SHOP else None)
    console._REV_CACHE.clear()
    d = console._revenue_data(force=True)
    assert d["mrr"] == 49.0 and d["arr"] == 588.0
    assert d["clients"][0]["source"] == "stripe" and d["clients"][0]["renewal"] == "2027-01-01"


def test_revenue_page_uses_manual_when_stripe_off(client):
    c, store = client
    _seed(store)
    _login(c)
    c.post("/console/settings", data={"tab": "revenue", f"rev_{SHOP}_amount": "500",
                                    f"rev_{SHOP}_renewal": "2026-08-01", f"rev_{SHOP}_status": "active"})
    html = c.get("/console/revenue").text
    assert "500" in html and "ARR" in html


# ── outreach send ────────────────────────────────────────────────────────────
def test_outreach_send_resolves_email_and_calls_brevo(client, monkeypatch):
    c, store = client
    _seed(store)
    import json as _json
    store.save_settings(SHOP, _json.dumps({"account_email": "ceo@acme.com"}))
    sent = {}
    import halia.notify as notify
    monkeypatch.setattr(notify, "email_configured", lambda: True)
    monkeypatch.setattr(notify, "send_email",
                        lambda to, subj, html, text=None, shop=None: sent.update(
                            {"to": to, "subj": subj, "shop": shop}) or True)
    _login(c)
    r = c.post("/console/outreach/send", json={"shop": SHOP, "template_id": "checkin"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert sent["to"] == "ceo@acme.com" and sent["shop"] == SHOP
    assert "Acme Fashion" in sent["subj"]        # {store} placeholder filled


def test_outreach_send_requires_session(client):
    c, _ = client
    assert c.post("/console/outreach/send", json={"shop": SHOP, "template_id": "checkin"}).status_code == 403


# ── _console_ok signature / expiry ─────────────────────────────────────────────
def test_console_ok_rejects_tampered_or_expired(monkeypatch):
    monkeypatch.setattr("halia.config.CONSOLE_KEY", "own3r")

    class _Req:
        def __init__(self, cookie):
            self.cookies = {"halia_console": cookie} if cookie else {}

    good = console._make_cookie()
    assert console._console_ok(_Req(good))
    assert not console._console_ok(_Req(""))                  # no cookie
    assert not console._console_ok(_Req("999|deadbeef"))      # bad signature
    exp, sig = good.split("|", 1)
    assert not console._console_ok(_Req(f"{int(exp) - 10**9}|{sig}"))  # expired -> sig no longer valid
