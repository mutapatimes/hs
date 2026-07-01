"""Quick-win dashboard surfaces: CSV export + Shopify tag write-back from the RAM cache."""
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


def _result(cid="123"):
    return ScoreResult(matched=True, flagged=True, tier="A1", grade="A*", score=99,
                       is_priority=True, signal_count=1, signals=["Work email"],
                       reasons="Work email: GS", gesture="", spend=400.0, hidden_vic=True,
                       customer_id=cid, email=f"{cid}@x.com", phone=None)


def _seed_cache():
    """One hidden VIC in the RAM cache: a result (for tagging) + a dashboard row (for CSV)."""
    payload = {"data": [{"name": "Jane Doe", "email": "jane@x.com", "phone": "+44 1",
                         "loc": "Chelsea, London", "grade": "A*", "score": 99, "spend": 400,
                         "latent": 12000, "count": 1,
                         "signals": [{"seg": "work-email", "d": "Work email: GS", "x": ""}],
                         "reco": "Personal, service-led approach."}]}
    cache.set(SHOP, [_result("123")], payload, [])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    store = ShopStore(db_path=tmp_path / "q.db")
    monkeypatch.setattr("halia.api.shopify_push.shop_store", lambda: store)
    yield TestClient(app), store
    cache.evict(SHOP)


# ── CSV export ───────────────────────────────────────────────────────────────
def test_export_returns_csv(client):
    tc, _ = client
    _seed_cache()
    r = tc.get("/v1/export", headers=_auth())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.text
    assert "Name,Email,Phone,Location,Grade,Score" in body.splitlines()[0]
    assert "Jane Doe" in body and "jane@x.com" in body and "12000" in body


def test_export_requires_session_token(client):
    tc, _ = client
    assert tc.get("/v1/export").status_code == 401


# ── Shopify tag write-back ───────────────────────────────────────────────────
class _FakeShopify:
    def __init__(self):
        self.calls = []

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        field = "metafieldsSet" if "metafieldsSet" in query else "tagsAdd"
        return {"data": {field: {"userErrors": []}}}


def test_shopify_push_tags_hidden_vics(client, monkeypatch):
    tc, store = client
    store.save_shop(SHOP, "shpat_test")
    _seed_cache()
    fake = _FakeShopify()
    monkeypatch.setattr("scoring.shopify_fetch.http_transport", lambda *a, **k: fake)

    r = tc.post("/v1/shopify/push", json={}, headers=_auth())
    assert r.status_code == 200 and r.json() == {"pushed": 1}
    # One metafieldsSet + one tagsAdd for the single hidden VIC.
    assert any("metafieldsSet" in q for q, _ in fake.calls)
    tags = [v for q, v in fake.calls if "tagsAdd" in q]
    assert tags and tags[0]["tags"] == ["Halia:A*"]


def test_shopify_push_rejects_woocommerce(client):
    tc, store = client
    store.create_tenant(SHOP, "woocommerce", "Woo store", "hash")
    _seed_cache()
    r = tc.post("/v1/shopify/push", json={}, headers=_auth())
    assert r.status_code == 400 and "WooCommerce" in r.json()["detail"]


def test_shopify_push_without_token(client):
    tc, _ = client
    _seed_cache()
    r = tc.post("/v1/shopify/push", json={}, headers=_auth())
    assert r.status_code == 400 and "No Shopify connection" in r.json()["detail"]


def test_shopify_push_requires_session_token(client):
    tc, _ = client
    assert tc.post("/v1/shopify/push", json={}).status_code == 401
