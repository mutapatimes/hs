"""HubSpot sink (upsert by email + properties) and the connect/status/push/list/disconnect routes.
No network: a fake transport is injected via hubspot_sink._http_transport."""
import pytest
from fastapi.testclient import TestClient

from halia.adapters import hubspot_sink as hs
from halia.api import shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.schema import ScoreResult
from halia.store import ShopStore


def res(email="vic@x.com", grade="A*", vic=True, signals=("Work email", "HNWI postcode")):
    return ScoreResult(matched=True, flagged=True, tier="A1", grade=grade, score=96,
                       is_priority=True, signal_count=len(signals), signals=list(signals),
                       reasons="; ".join(signals), gesture="", spend=420.0, hidden_vic=vic,
                       customer_id="c1", email=email, phone=None)


class FakeHubSpot:
    """Records every (method, path, body); answers as HubSpot would for the happy path."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and "properties/contacts" in path:
            return 200, {"results": []}                 # no Halia props yet -> sink will create them
        if method == "GET" and "objects/contacts" in path:
            return 200, {"results": []}                 # validate_token probe
        if "batch/upsert" in path:
            inputs = (body or {}).get("inputs", [])
            return 200, {"results": [{"id": str(1000 + i), "properties": {"email": x["id"]}}
                                     for i, x in enumerate(inputs)]}
        if path == "/crm/v3/lists":
            return 201, {"list": {"listId": "L1"}}
        return 200, {}


@pytest.fixture()
def fake(monkeypatch):
    f = FakeHubSpot()
    monkeypatch.setattr(hs, "_http_transport", lambda token: f)
    return f


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "h.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    yield TestClient(app), store


def _tenant(store, shop="shoph"):
    tok = new_token()
    store.create_tenant(shop, "woocommerce", "Shop", hash_token(tok))
    return tok


# ── sink ────────────────────────────────────────────────────────────────────────
def test_ensure_properties_creates_halia_fields(fake):
    hs.HubSpotSink("pat-x").ensure_properties()
    created = {b["name"] for (m, p, b) in fake.calls if m == "POST" and p.endswith("/properties/contacts")}
    assert {"halia_grade", "halia_score", "halia_vic"} <= created


def test_upsert_writes_grade_and_reasons_by_email(fake):
    got = hs.HubSpotSink("pat-x").upsert([res("a@b.com")], scored_at="2026-01-01T00:00:00")
    up = next(b for (m, p, b) in fake.calls if "batch/upsert" in p)
    inp = up["inputs"][0]
    assert inp["idProperty"] == "email" and inp["id"] == "a@b.com"
    assert inp["properties"]["halia_grade"] == "A*" and "Work email" in inp["properties"]["halia_reasons"]
    assert inp["properties"]["halia_vic"] == "Yes"
    assert got and got[0]["id"] == "1000"          # contact id returned for list-building


def test_push_many_skips_no_email(fake):
    n = hs.HubSpotSink("pat-x").push_many([res("a@b.com"), res(email=None)])
    assert n == 1                                   # the emailless result is skipped


# ── routes ──────────────────────────────────────────────────────────────────────
def test_connect_status_disconnect(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    r = c.post("/v1/hubspot/connect", json={"api_token": "pat-abc"})
    assert r.status_code == 200 and r.json()["connected"] is True
    assert store.get_hubspot("shoph")["api_token"] == "pat-abc"
    # properties were provisioned on connect
    assert any(m == "POST" and p.endswith("/properties/contacts") for (m, p, b) in fake.calls)
    assert c.get("/v1/hubspot/status").json()["connected"] is True
    assert c.post("/v1/hubspot/disconnect").json() == {"connected": False}
    assert store.get_hubspot("shoph") is None


def test_connect_rejects_empty_token(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/hubspot/connect", json={"api_token": "  "}).status_code == 422


def test_push_hidden_vics(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    store.save_hubspot("shoph", "pat-abc", "")
    cache.set("shoph", [res("vic@x.com")], {"data": []}, [])
    try:
        r = c.post("/v1/hubspot/push", json={})
        assert r.status_code == 200 and r.json()["pushed"] == 1
    finally:
        cache.evict("shoph")


def test_push_requires_connection(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    cache.set("shoph", [res()], {"data": []}, [])
    try:
        assert c.post("/v1/hubspot/push", json={}).status_code == 400
    finally:
        cache.evict("shoph")


def test_list_creates_static_list_from_selection(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    store.save_hubspot("shoph", "pat-abc", "")
    cache.set("shoph", [res("vic@x.com")], {"data": []}, [])
    try:
        r = c.post("/v1/hubspot/list", json={"customer_ids": ["c1"], "name": "VIPs"})
        assert r.status_code == 200 and r.json()["list"]["id"] == "L1" and r.json()["count"] == 1
        assert any(p == "/crm/v3/lists" for (m, p, b) in fake.calls)          # a list was created
    finally:
        cache.evict("shoph")
