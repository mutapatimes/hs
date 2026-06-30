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
    monkeypatch.setattr(onboarding, "_start_sync", lambda shop: None)
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
    assert billing._verify_sig(body, f"t=123,v1={good}", secret) is True
    assert billing._verify_sig(body, "t=123,v1=deadbeef", secret) is False
