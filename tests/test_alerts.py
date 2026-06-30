"""High-grade order alerts: feed builder + /v1/alerts endpoint + settings."""
import pytest
from fastapi.testclient import TestClient

from halia.api import data, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

ENTRY = {
    "results": [],
    "payload": {"data": [
        {"id": "C-0001", "cid": "7", "email": "amara@blackstone.com", "name": "Amara Okonkwo",
         "grade": "A*", "score": 96, "spend": 420, "signals": [{"d": "Work email: Blackstone"}]},
        {"id": "C-0002", "cid": "9", "email": "bob@gmail.com", "name": "Bob Smith",
         "grade": "B", "score": 60, "spend": 80, "signals": [{"d": "Premium email"}]},
    ]},
    "orders": [
        {"order_id": "1001", "created_at": "2026-06-30T10:00:00", "customer_id": "7", "email": "amara@blackstone.com"},
        {"order_id": "1002", "created_at": "2026-06-29T10:00:00", "customer_id": "9", "email": "bob@gmail.com"},
        {"order_id": "1003", "created_at": "2026-06-30T12:00:00", "customer_id": "7", "email": "amara@blackstone.com"},
    ],
}


def test_high_grade_orders_filters_and_sorts():
    out = data.high_grade_orders(ENTRY, grades=("A*", "A"))
    assert [a["order_id"] for a in out] == ["1003", "1001"]   # B excluded, newest first
    assert out[0]["name"] == "Amara Okonkwo" and out[0]["grade"] == "A*"
    assert out[0]["signals"] == ["Work email"]


def test_high_grade_orders_grade_threshold():
    assert data.high_grade_orders(ENTRY, grades=("A*",))  # A* only still matches Amara
    assert data.high_grade_orders(ENTRY, grades=("A",)) == []  # no plain-A clients here


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "a.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    yield TestClient(app), store


def test_alerts_endpoint(client):
    c, store = client
    tok = new_token()
    store.create_tenant("shopa", "woocommerce", "Shop", hash_token(tok))
    cache.set("shopa", ENTRY["results"], ENTRY["payload"], ENTRY["orders"])
    c.cookies.set(COOKIE, tok)
    r = c.get("/v1/alerts")
    assert r.status_code == 200
    assert [a["order_id"] for a in r.json()] == ["1003", "1001"]


def test_settings_carry_notify_fields(client):
    c, store = client
    tok = new_token()
    store.create_tenant("shopa", "woocommerce", "Shop", hash_token(tok))
    c.cookies.set(COOKIE, tok)
    assert c.get("/v1/settings").json()["notify_grades"] == ["A*", "A"]
    c.post("/v1/settings", json={"notify_enabled": True, "notify_grades": ["A*"]})
    s = c.get("/v1/settings").json()
    assert s["notify_enabled"] is True and s["notify_grades"] == ["A*"]
