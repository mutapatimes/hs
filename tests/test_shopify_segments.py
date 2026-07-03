"""Shopify segment creation: the adapter mutation + the /v1/shopify/segment route (fake transport)."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import scoring.shopify_fetch as sf
from halia.adapters import shopify_segments as seg
from halia.api import shopify_auth
from halia.api.app import app
from halia.cache import cache
from halia.schema import ScoreResult
from halia.store import ShopStore

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _result(cid="123"):
    return ScoreResult(matched=True, flagged=True, tier="A1", grade="A*", score=99,
                       is_priority=True, signal_count=1, signals=["Work email"],
                       reasons="Work email: GS", gesture="", spend=400.0, hidden_vic=True,
                       customer_id=cid, email=f"{cid}@x.com", phone=None)


def _seed_cache():
    cache.set(SHOP, [_result("123")], {"data": []}, [])


class FakeShopify:
    """Records (query, variables); answers segmentCreate / tagsAdd / metafieldsSet cleanly."""

    def __init__(self):
        self.calls = []

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        if "segmentCreate" in query:
            return {"data": {"segmentCreate": {
                "segment": {"id": "gid://shopify/Segment/555", "name": variables["name"]},
                "userErrors": []}}}
        if "tagsAdd" in query:
            return {"data": {"tagsAdd": {"userErrors": []}}}
        return {"data": {"metafieldsSet": {"userErrors": []}}}


@pytest.fixture()
def fake(monkeypatch):
    f = FakeShopify()
    monkeypatch.setattr(sf, "http_transport", lambda *a, **k: f)
    return f


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    store = ShopStore(db_path=tmp_path / "seg.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    yield TestClient(app), store
    cache.evict(SHOP)


# ── adapter ──────────────────────────────────────────────────────────────────────
def test_adapter_create_segment(fake):
    out = seg.create_segment(fake, "My VIPs", "customer_tags CONTAINS 'Halia:my-vips'")
    assert out == {"id": "gid://shopify/Segment/555", "name": "My VIPs"}
    q, v = fake.calls[-1]
    assert "segmentCreate" in q and v == {"name": "My VIPs", "query": "customer_tags CONTAINS 'Halia:my-vips'"}


def test_segment_numeric_id():
    assert seg.segment_numeric_id("gid://shopify/Segment/555") == "555"


# ── route ────────────────────────────────────────────────────────────────────────
def test_create_segment_from_selection(client, fake):
    c, store = client
    store.save_shop(SHOP, "shpat_x")
    _seed_cache()
    r = c.post("/v1/shopify/segment", json={"customer_ids": ["123"], "name": "VIP list"}, headers=_auth())
    assert r.status_code == 200
    d = r.json()
    assert d["count"] == 1 and d["segment"]["id"] == "gid://shopify/Segment/555"
    assert d["admin_url"] == f"https://{SHOP}/admin/customers/segments/555"
    # the selection was tagged, and the segment queries that exact tag
    tag_calls = [v for q, v in fake.calls if "tagsAdd" in q]
    assert tag_calls and tag_calls[0]["tags"] == ["Halia:vip-list"]
    seg_call = next(v for q, v in fake.calls if "segmentCreate" in q)
    assert seg_call["query"] == "customer_tags CONTAINS 'Halia:vip-list'"


def test_rejects_non_shopify_tenant(client, fake):
    c, store = client
    store.create_tenant(SHOP, "woocommerce", "Woo", "hash")
    _seed_cache()
    r = c.post("/v1/shopify/segment", json={"customer_ids": ["123"], "name": "x"}, headers=_auth())
    assert r.status_code == 400 and "Shopify" in r.json()["detail"]


def test_requires_a_shopify_token(client, fake):
    c, _ = client
    _seed_cache()      # no token saved, no tenant row
    r = c.post("/v1/shopify/segment", json={"customer_ids": ["123"], "name": "x"}, headers=_auth())
    assert r.status_code == 400 and "No Shopify connection" in r.json()["detail"]


def test_empty_selection_rejected(client, fake):
    c, store = client
    store.save_shop(SHOP, "shpat_x")
    _seed_cache()
    r = c.post("/v1/shopify/segment", json={"customer_ids": [], "name": "x"}, headers=_auth())
    assert r.status_code == 400 and "No customers selected" in r.json()["detail"]
