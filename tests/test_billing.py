"""Freemium gating + Stripe billing."""
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from halia.api import billing, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "b.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    return TestClient(app), store


def _tenant(store, shop="shopx"):
    tok = new_token()
    store.create_tenant(shop, "woocommerce", "Shop X", hash_token(tok))
    return tok


def _enable(monkeypatch):
    monkeypatch.setattr("halia.config.STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr("halia.config.STRIPE_PRICE_ID", "price_x")
    monkeypatch.setattr("halia.config.STRIPE_WEBHOOK_SECRET", None)
    monkeypatch.setattr("halia.config.HALIA_FREE_SHOPS", set())


def test_storeconcierge_tenant_gets_its_own_flat_price_and_plan(client, monkeypatch):
    _, store = client
    monkeypatch.setattr("halia.config.STRIPE_PRICE_ID", "price_halia")
    monkeypatch.setattr("halia.config.STRIPE_TIERS",
                        "15000:price_discovery,75000:price_signal,*:price_atelier")
    monkeypatch.setattr("halia.config.STRIPE_PRICE_STORECONCIERGE", "price_sc14")
    from halia.storeconcierge.tenant import set_brand
    store.create_tenant("scshop", "woocommerce", "SC Shop", "h")
    # a Halia tenant still gets a size tier
    store.create_tenant("haliashop", "woocommerce", "Halia Shop", "h")
    assert billing.price_for_shop("haliashop") == "price_discovery"
    # the Store Concierge tenant gets its own flat price + plan name
    set_brand("scshop", "storeconcierge")
    assert billing.price_for_shop("scshop") == "price_sc14"
    assert billing.plan_for_shop("scshop")["name"] == "Store Concierge"
    # falls back to the Halia price if the SC price isn't configured
    monkeypatch.setattr("halia.config.STRIPE_PRICE_STORECONCIERGE", None)
    assert billing.price_for_shop("scshop") == "price_discovery"


def test_billing_plans_endpoint_carries_stripe_links_and_recommendation(client, monkeypatch):
    c, store = client
    tok = _tenant(store, "shopx")
    _enable(monkeypatch)
    monkeypatch.setattr("halia.config.STRIPE_TIERS",
                        "15000:price_discovery,75000:price_signal,*:price_atelier")
    monkeypatch.setattr("halia.config.STRIPE_PLAN_LINKS",
                        "discovery=https://buy.stripe.com/d,signal=https://buy.stripe.com/s")
    from halia.api.tenant_auth import COOKIE
    r = c.get("/v1/billing/plans", cookies={COOKIE: tok})
    assert r.status_code == 200
    j = r.json()
    by = {p["key"]: p for p in j["plans"]}
    assert [p["key"] for p in j["plans"]] == ["free", "discovery", "signal", "atelier", "maison"]
    # the shop rides along as Stripe's client_reference_id so the webhook can trace the checkout
    assert by["signal"]["link"] == "https://buy.stripe.com/s?client_reference_id=shopx"
    assert by["free"]["link"] == "" and by["maison"]["link"] == ""
    assert j["enabled"] is True and "recommended" in j


def test_billing_plans_storeconcierge_gets_its_own_single_card(client, monkeypatch):
    c, store = client
    tok = _tenant(store, "scshop")
    _enable(monkeypatch)
    monkeypatch.setattr("halia.config.STRIPE_PLAN_LINKS",
                        "signal=https://buy.stripe.com/s,storeconcierge=https://buy.stripe.com/sc")
    from halia.storeconcierge.tenant import set_brand
    set_brand("scshop", "storeconcierge")
    from halia.api.tenant_auth import COOKIE
    j = c.get("/v1/billing/plans", cookies={COOKIE: tok}).json()
    assert [p["key"] for p in j["plans"]] == ["storeconcierge"]        # not the Halia tiers
    card = j["plans"][0]
    assert card["priceLabel"] == "£14"
    assert card["link"] == "https://buy.stripe.com/sc?client_reference_id=scshop"
    assert j["recommended"] == "Store Concierge"


def test_webhook_maps_payment_link_cancellation_back_to_shop(client):
    c, store = client
    # a Payment Link checkout activated this shop, storing the Stripe subscription id
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    # the later subscription.deleted event carries NO shop reference, only the subscription id
    ev = {"type": "customer.subscription.deleted",
          "data": {"object": {"id": "sub_1", "customer": "cus_1"}}}
    r = c.post("/webhooks/stripe", json=ev)
    assert r.status_code == 200
    assert store.get_billing("shopx")["status"] == "canceled"    # mapped back and cancelled


def test_plan_links_parsing():
    monkey = {"STRIPE_PLAN_LINKS": "signal=https://buy.stripe.com/x , bad=notaurl,=skip,"
                                   "atelier=https://buy.stripe.com/y"}
    import halia.config as cfg
    orig = cfg.STRIPE_PLAN_LINKS
    try:
        cfg.STRIPE_PLAN_LINKS = monkey["STRIPE_PLAN_LINKS"]
        links = billing.plan_links()
        assert links == {"signal": "https://buy.stripe.com/x",
                         "atelier": "https://buy.stripe.com/y"}   # bad/empty dropped
    finally:
        cfg.STRIPE_PLAN_LINKS = orig


def test_is_paid_open_when_billing_off(client, monkeypatch):
    monkeypatch.setattr("halia.config.STRIPE_SECRET_KEY", None)
    assert billing.is_paid("anyshop") is True


def test_is_paid_gates_when_enabled(client, monkeypatch):
    _, store = client
    _enable(monkeypatch)
    assert billing.is_paid("shopx") is False
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    assert billing.is_paid("shopx") is True


def test_free_shops_are_comped(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr("halia.config.HALIA_FREE_SHOPS", {"vipshop"})
    assert billing.is_paid("vipshop") is True
    assert billing.is_paid("other") is False


def test_store_billing_roundtrip(client):
    _, store = client
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    b = store.get_billing("shopx")
    assert b["status"] == "active" and b["customer_id"] == "cus_1"
    store.set_billing("shopx", "canceled")               # status-only update keeps the ids
    b = store.get_billing("shopx")
    assert b["status"] == "canceled" and b["customer_id"] == "cus_1"


def test_checkout_noop_when_billing_off(client, monkeypatch):
    c, store = client
    monkeypatch.setattr("halia.config.STRIPE_SECRET_KEY", None)
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/checkout").json() == {"url": "/app"}


def test_checkout_creates_session(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    monkeypatch.setattr(billing, "create_checkout", lambda shop: f"https://checkout.stripe/{shop}")
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/checkout").json() == {"url": "https://checkout.stripe/shopx"}


def test_billing_status_free_then_active(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    c.cookies.set(COOKIE, _tenant(store))
    s = c.get("/v1/billing/status").json()
    assert s["enabled"] and s["paid"] is False and s["status"] == "free" and s["manageable"] is False
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    s = c.get("/v1/billing/status").json()
    assert s["paid"] and s["status"] == "active" and s["manageable"] is True


def test_billing_status_open_when_billing_off(client, monkeypatch):
    c, store = client
    monkeypatch.setattr("halia.config.STRIPE_SECRET_KEY", None)
    c.cookies.set(COOKIE, _tenant(store))
    s = c.get("/v1/billing/status").json()
    assert s["enabled"] is False and s["paid"] is True and s["manageable"] is False


def test_portal_opens_for_customer(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    store.set_billing("shopx", "active", "cus_9", "sub_9")
    monkeypatch.setattr(billing, "_stripe",
                        lambda m, p, data=None: {"url": f"https://portal.stripe/{data['customer']}"})
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/billing/portal").json() == {"url": "https://portal.stripe/cus_9"}


def test_portal_400_without_customer(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/billing/portal").status_code == 400  # no customer yet


def test_cancel_schedules_at_period_end(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    calls = {}
    monkeypatch.setattr(billing, "_stripe",
                        lambda m, p, data=None: calls.update(path=p, data=data)
                        or {"cancel_at_period_end": data.get("cancel_at_period_end") == "true",
                            "current_period_end": 1893456000})
    c.cookies.set(COOKIE, _tenant(store))
    r = c.post("/v1/billing/cancel").json()
    assert calls["path"] == "subscriptions/sub_1" and calls["data"]["cancel_at_period_end"] == "true"
    assert r["cancel_at_period_end"] is True and r["current_period_end"] == 1893456000
    # still paid until the period actually ends (Stripe keeps status active)
    assert billing.is_paid("shopx") is True


def test_resume_undoes_cancellation(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    monkeypatch.setattr(billing, "_stripe",
                        lambda m, p, data=None: {"cancel_at_period_end": data.get("cancel_at_period_end") == "true"})
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/billing/resume").json()["cancel_at_period_end"] is False


def test_cancel_400_without_subscription(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    store.set_billing("shopx", "active", "cus_1")  # no subscription_id
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/billing/cancel").status_code == 400


def test_status_reports_scheduled_cancellation(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    monkeypatch.setattr(billing, "_stripe",
                        lambda m, p, data=None: {"cancel_at_period_end": True, "current_period_end": 111})
    c.cookies.set(COOKIE, _tenant(store))
    s = c.get("/v1/billing/status").json()
    assert s["cancellable"] and s["cancel_at_period_end"] is True and s["current_period_end"] == 111


def test_retention_applies_discount(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    calls = []
    monkeypatch.setattr(billing, "_stripe",
                        lambda m, p, data=None: calls.append((p, data))
                        or ({"id": "co_50"} if p == "coupons" else {"ok": True}))
    c.cookies.set(COOKIE, _tenant(store))
    r = c.post("/v1/billing/retention").json()
    assert r["ok"] and r["percent_off"] == 50
    # created an ad-hoc 50% coupon and applied it to the subscription
    assert ("coupons", {"percent_off": "50", "duration": "forever",
                        "name": "Halia retention 50% off"}) in calls
    assert ("subscriptions/sub_1", {"coupon": "co_50"}) in calls


def test_retention_uses_configured_coupon(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    monkeypatch.setattr("halia.config.STRIPE_RETENTION_COUPON", "co_fixed")
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    seen = {}
    monkeypatch.setattr(billing, "_stripe", lambda m, p, data=None: seen.update(p=p, data=data) or {})
    c.cookies.set(COOKIE, _tenant(store))
    c.post("/v1/billing/retention")
    assert seen == {"p": "subscriptions/sub_1", "data": {"coupon": "co_fixed"}}  # no coupon created


def test_cancel_records_reason_and_schedules(client, monkeypatch):
    import json
    c, store = client
    _enable(monkeypatch)
    store.set_billing("shopx", "active", "cus_1", "sub_1")
    monkeypatch.setattr(billing, "_stripe",
                        lambda m, p, data=None: {"cancel_at_period_end": True, "current_period_end": 123})
    c.cookies.set(COOKIE, _tenant(store))
    r = c.post("/v1/billing/cancel", json={"reason": "Too expensive", "detail": "tight month"}).json()
    assert r["cancel_at_period_end"] is True
    # self-service: access continues until period end (Stripe keeps status active)
    assert billing.is_paid("shopx") is True
    # survey reason recorded for our team
    s = json.loads(store.get_settings_raw("shopx"))
    assert s["cancel_reason"] == "Too expensive" and s["cancel_detail"] == "tight month"


def test_app_shows_teaser_when_unpaid(client, monkeypatch):
    c, store = client
    _enable(monkeypatch)
    tok = _tenant(store)
    cache.set("shopx", [], {"stat_count": "7", "stat_latent": "£42,000", "stat_toptier": "3"}, {})
    try:
        c.cookies.set(COOKIE, tok)
        r = c.get("/app")
        assert r.status_code == 200
        assert "Unlock this hidden revenue" in r.text
        assert "£42,000" in r.text and "7" in r.text
    finally:
        cache.evict("shopx")


def test_webhook_marks_active(client):
    c, store = client
    _tenant(store)
    event = {"type": "checkout.session.completed",
             "data": {"object": {"client_reference_id": "shopx",
                                  "customer": "cus_9", "subscription": "sub_9"}}}
    assert c.post("/webhooks/stripe", json=event).json() == {"received": True}
    assert store.get_billing("shopx")["status"] == "active"


def test_webhook_signature():
    secret = "whsec_test"
    body = b'{"hello":"world"}'
    good = hmac.new(secret.encode(), b"123." + body, hashlib.sha256).hexdigest()
    # tolerance=0 disables the freshness window so this fixed-timestamp signature check is stable
    assert billing._verify_sig(body, f"t=123,v1={good}", secret, tolerance=0) is True
    assert billing._verify_sig(body, "t=123,v1=deadbeef", secret, tolerance=0) is False


# ── size-based pricing tiers ─────────────────────────────────────────────────────
def test_tier_parsing_and_selection(monkeypatch):
    monkeypatch.setattr("halia.config.STRIPE_TIERS",
                        "15k:price_discovery, 50000:price_growth, *:price_enterprise")
    assert billing._parse_tiers() == [(15000.0, "price_discovery"),
                                       (50000.0, "price_growth"),
                                       (float("inf"), "price_enterprise")]

    def price_at(n):
        monkeypatch.setattr(billing, "_scanned_count", lambda shop: n)
        return billing.price_for_shop("shopx")

    assert price_at(0) == "price_discovery"          # cold/empty cache -> smallest tier
    assert price_at(15000) == "price_discovery"      # cap is inclusive
    assert price_at(15001) == "price_growth"
    assert price_at(50000) == "price_growth"
    assert price_at(200000) == "price_enterprise"    # above every finite cap -> top tier


def test_billing_enabled_with_tiers_but_no_single_price(monkeypatch):
    monkeypatch.setattr("halia.config.STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr("halia.config.STRIPE_PRICE_ID", None)
    monkeypatch.setattr("halia.config.STRIPE_TIERS", "*:price_x")
    assert billing.billing_enabled() is True


def test_price_falls_back_to_single_when_no_tiers(monkeypatch):
    monkeypatch.setattr("halia.config.STRIPE_TIERS", None)
    monkeypatch.setattr("halia.config.STRIPE_PRICE_ID", "price_single")
    assert billing.price_for_shop("shopx") == "price_single"


def test_plan_for_shop_matches_by_book_size(monkeypatch):
    monkeypatch.setattr("halia.config.STRIPE_TIERS",
                        "15000:price_a, 75000:price_b, *:price_c")
    monkeypatch.setattr(billing, "_scanned_count", lambda shop: 47015)
    plan = billing.plan_for_shop("shopx")
    assert plan == {"name": "Signal", "count": 47015}
    monkeypatch.setattr(billing, "_scanned_count", lambda shop: 8000)
    assert billing.plan_for_shop("shopx")["name"] == "Discovery"
    monkeypatch.setattr(billing, "_scanned_count", lambda shop: 200000)
    assert billing.plan_for_shop("shopx")["name"] == "Atelier"


def test_plan_none_without_tiers(monkeypatch):
    monkeypatch.setattr("halia.config.STRIPE_TIERS", "")
    assert billing.plan_for_shop("shopx") is None


def test_webhook_marks_paid_with_valid_signature(monkeypatch):
    import hashlib, hmac as _h, json as _j, time as _t
    from fastapi.testclient import TestClient
    from halia.api.app import app
    from halia import config
    monkeypatch.setattr(billing, "billing_enabled", lambda: True)
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_x")
    recorded = {}
    monkeypatch.setattr(billing.shop_store(), "set_billing",
                        lambda shop, status, *a, **k: recorded.update(shop=shop, status=status))
    body = _j.dumps({"type": "checkout.session.completed",
                     "data": {"object": {"client_reference_id": "acme.myshopify.com",
                                          "customer": "cus_1", "subscription": "sub_1"}}}).encode()
    t = str(int(_t.time()))
    sig = _h.new(b"whsec_x", t.encode() + b"." + body, hashlib.sha256).hexdigest()
    r = TestClient(app).post("/webhooks/stripe", content=body,
                             headers={"stripe-signature": f"t={t},v1={sig}",
                                      "content-type": "application/json"})
    assert r.status_code == 200 and recorded == {"shop": "acme.myshopify.com", "status": "active"}
