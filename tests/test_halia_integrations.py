"""Klaviyo integration routes (cache-backed) + order-history mapping."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia.api.app import app
from halia.api.data import _history
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
    monkeypatch.setattr("halia.config.KLAVIYO_API_KEY", None)  # force "not connected"
    monkeypatch.setattr("halia.api.integrations.shop_store",
                        lambda: ShopStore(db_path=tmp_path / "i.db"))  # no stored key
    yield TestClient(app)


def test_push_without_key_asks_to_connect(client):
    r = client.post("/v1/klaviyo/push", json={}, headers=_auth())
    assert r.status_code == 400 and "Connect Klaviyo" in r.json()["detail"]


def test_event_without_key_asks_to_connect(client):
    r = client.post("/v1/klaviyo/event", json={"customer_id": "c1"}, headers=_auth())
    assert r.status_code == 400 and "Connect Klaviyo" in r.json()["detail"]


def test_connect_rejects_non_private_key(client):
    assert client.post("/v1/klaviyo/connect", json={"api_key": "nope"}, headers=_auth()).status_code == 422


def test_status_reflects_no_connection(client):
    assert client.get("/v1/klaviyo/status", headers=_auth()).json() == {"connected": False}


def test_routes_require_session_token(client):
    assert client.post("/v1/klaviyo/push", json={}).status_code == 401


def test_fire_event_builds_metric_and_profile():
    from halia.adapters.klaviyo_events import METRIC, fire_event
    from halia.schema import ScoreResult

    result = ScoreResult(matched=True, flagged=True, tier="A1", grade="A*", score=99,
                         is_priority=True, signal_count=1, signals=[], reasons="Work email: GS",
                         gesture="", spend=400.0, hidden_vic=True, customer_id="c1",
                         email="vic@x.com", phone=None)
    cap = {}

    def fake(url, key, rev, body):
        cap.update(url=url, key=key, body=body)
        return 202, {}

    fire_event("pk_test", result, transport=fake)
    attrs = cap["body"]["data"]["attributes"]
    assert cap["url"].endswith("/api/events") and cap["key"] == "pk_test"
    assert attrs["metric"]["data"]["attributes"]["name"] == METRIC
    assert attrs["profile"]["data"]["attributes"]["email"] == "vic@x.com"
    assert attrs["properties"]["halia_grade"] == "A*" and attrs["value"] == 400.0


def test_list_route_without_key(client):
    r = client.post("/v1/klaviyo/list", json={"customer_ids": ["c1"]}, headers=_auth())
    assert r.status_code == 400 and "Connect Klaviyo" in r.json()["detail"]


def test_create_list_and_add_profiles_bodies():
    from halia.adapters.klaviyo_lists import add_profiles, create_list
    cap = {}

    def fake_create(url, key, rev, body):
        cap["create"] = (url, body)
        return 201, {"data": {"id": "LST1"}}

    assert create_list("pk_x", "My List", transport=fake_create) == "LST1"
    assert cap["create"][0].endswith("/api/lists")
    assert cap["create"][1]["data"]["attributes"]["name"] == "My List"

    def fake_add(url, key, rev, body):
        cap["add"] = (url, body)
        return 204, {}

    add_profiles("pk_x", "LST1", ["p1", "p2"], transport=fake_add)
    assert cap["add"][0].endswith("/api/lists/LST1/relationships/profiles")
    assert [d["id"] for d in cap["add"][1]["data"]] == ["p1", "p2"]


def test_history_groups_and_sorts():
    orders = [
        {"customer": {"id": "c1"}, "created_at": "2026-03-01T10:00:00Z",
         "total_price": "100.0", "line_items": [{"quantity": 2}]},
        {"customer": {"id": "c1"}, "created_at": "2026-05-01T10:00:00Z",
         "total_price": "250.0", "line_items": [{"quantity": 1}, {"quantity": 1}]},
    ]
    by = _history(orders)
    assert [o["date"] for o in by["c1"]] == ["2026-05-01", "2026-03-01"]  # newest first
    assert by["c1"][0]["items"] == 2 and by["c1"][0]["amount"] == 250.0
