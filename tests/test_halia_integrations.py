"""Klaviyo integration routes + order-history mapping (no network)."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia.api.app import app
from halia.api.embedded import _orders_by_customer
from halia.store import ScoreStore

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    monkeypatch.setattr("halia.config.KLAVIYO_API_KEY", None)  # force "not connected"
    app.state.store = ScoreStore(db_path=tmp_path / "i.db")
    yield TestClient(app)
    app.state.store = None


def test_push_without_a_key_asks_to_connect(client):
    r = client.post("/v1/klaviyo/push", json={}, headers=_auth())
    assert r.status_code == 400 and "Connect Klaviyo" in r.json()["detail"]


def test_connect_rejects_non_private_key(client):
    r = client.post("/v1/klaviyo/connect", json={"api_key": "not-a-pk"}, headers=_auth())
    assert r.status_code == 422


def test_status_reflects_no_connection(client):
    assert client.get("/v1/klaviyo/status", headers=_auth()).json() == {"connected": False}


def test_routes_require_session_token(client):
    assert client.post("/v1/klaviyo/push", json={}).status_code == 401


def test_orders_by_customer_groups_and_sorts():
    orders = [
        {"customer": {"id": "c1"}, "created_at": "2026-03-01T10:00:00Z",
         "total_price": "100.0", "line_items": [{"quantity": 2}]},
        {"customer": {"id": "c1"}, "created_at": "2026-05-01T10:00:00Z",
         "total_price": "250.0", "line_items": [{"quantity": 1}, {"quantity": 1}]},
        {"customer": {"id": "c2"}, "created_at": "2026-04-01T10:00:00Z",
         "total_price": "50.0", "line_items": [{"quantity": 1}]},
    ]
    by = _orders_by_customer(orders)
    assert [o["date"] for o in by["c1"]] == ["2026-05-01", "2026-03-01"]  # newest first
    assert by["c1"][0]["items"] == 2 and by["c1"][0]["amount"] == 250.0
    assert by["c2"][0]["amount"] == 50.0
