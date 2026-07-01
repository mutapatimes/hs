"""POS tile lookup: GET /v1/pos/score — warm-cache first, single-customer live fallback, CORS."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia.api.app import app
from halia.cache import cache
from halia.schema import ScoreResult
from halia.store import ShopStore

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _vic(cid="123"):
    return ScoreResult(matched=True, flagged=True, tier="A1", grade="A*", score=95,
                       is_priority=True, signal_count=2, signals=["Work email", "HNWI postcode"],
                       reasons="Work email: GS; HNWI postcode: SW1X", gesture="Offer a coffee, low-key.",
                       spend=400.0, hidden_vic=True, customer_id=cid, email="j@x.com", phone=None)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    store = ShopStore(db_path=tmp_path / "p.db")
    monkeypatch.setattr("halia.api.app.shop_store", lambda: store)
    yield TestClient(app), store, monkeypatch
    cache.evict(SHOP)


# ── warm cache path ──────────────────────────────────────────────────────────
def test_cache_hit_returns_compact_vic(client):
    tc, _, _ = client
    cache.set(SHOP, [_vic("123")], {}, [])
    d = tc.get("/v1/pos/score?customer_id=123", headers=_auth()).json()
    assert d["matched"] and d["vic"] is True and d["grade"] == "A*"
    assert d["gesture"] and d["signals"] == ["Work email", "HNWI postcode"]
    assert d["hidden_vic"] is True


def test_cache_hit_normalises_gid_vs_numeric(client):
    tc, _, _ = client
    cache.set(SHOP, [_vic("gid://shopify/Customer/123")], {}, [])
    d = tc.get("/v1/pos/score?customer_id=123", headers=_auth()).json()  # POS sends numeric
    assert d["matched"] and d["grade"] == "A*"


# ── live fallback path (cache miss) ──────────────────────────────────────────
def test_cache_miss_unknown_customer(client):
    tc, store, mp = client
    store.save_shop(SHOP, "shpat_test")
    mp.setattr("scoring.shopify_fetch.fetch_customer_orders", lambda *a, **k: [])
    d = tc.get("/v1/pos/score?customer_id=999", headers=_auth()).json()
    assert d == {"matched": False}


def test_cache_miss_without_token_is_no_match(client):
    tc, _, _ = client  # no token saved
    d = tc.get("/v1/pos/score?customer_id=999", headers=_auth()).json()
    assert d == {"matched": False}


# ── guards ───────────────────────────────────────────────────────────────────
def test_requires_a_param(client):
    tc, _, _ = client
    assert tc.get("/v1/pos/score", headers=_auth()).status_code == 422


def test_requires_session_token(client):
    tc, _, _ = client
    assert tc.get("/v1/pos/score?customer_id=1").status_code == 401


# ── CORS preflight for the POS webview ───────────────────────────────────────
def test_cors_preflight_allows_shopify_cdn(client):
    tc, _, _ = client
    r = tc.options("/v1/pos/score", headers={"Origin": "https://cdn.shopify.com",
                                             "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://cdn.shopify.com"
