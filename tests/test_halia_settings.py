"""Merchant settings routes: defaults, save/reload, Klaviyo disconnect."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia.api.app import app
from halia.store import ShopStore

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    monkeypatch.setattr("halia.config.KLAVIYO_API_KEY", None)
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    yield TestClient(app), store


def test_defaults(client):
    c, _ = client
    s = c.get("/v1/settings", headers=_auth()).json()
    assert s["vic_threshold"] == 5000 and s["klaviyo_connected"] is False
    assert len(s["email_templates"]) >= 5
    assert "{first_name}" in s["email_templates"][0]["body"]
    assert s["aov"] == 0 and s["max_orders"] == 0 and s["highest_lt"] == 0  # latent benchmarks


def test_save_and_reload(client):
    c, _ = client
    r = c.post("/v1/settings", headers=_auth(), json={
        "vic_threshold": 8000, "sender_name": "The Team",
        "aov": 1800, "max_orders": 22, "highest_lt": 95000,
        "email_templates": [{"name": "Hi", "subject": "S", "body": "Dear {first_name}"},
                            {"name": "", "body": ""}]})  # blank one is dropped
    assert r.status_code == 200
    s = c.get("/v1/settings", headers=_auth()).json()
    assert s["vic_threshold"] == 8000 and s["sender_name"] == "The Team"
    assert s["aov"] == 1800 and s["max_orders"] == 22 and s["highest_lt"] == 95000
    assert len(s["email_templates"]) == 1 and s["email_templates"][0]["name"] == "Hi"


def test_klaviyo_disconnect(client):
    c, store = client
    store.save_klaviyo(SHOP, "pk_x")
    assert c.get("/v1/settings", headers=_auth()).json()["klaviyo_connected"] is True
    assert c.post("/v1/klaviyo/disconnect", headers=_auth()).status_code == 200
    assert store.get_klaviyo(SHOP) is None


def test_requires_session_token(client):
    c, _ = client
    assert c.get("/v1/settings").status_code == 401
