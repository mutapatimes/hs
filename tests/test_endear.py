"""Endear sink (bulkUpsertExternalCustomers by external id + tags + custom fields) and the
connect/status/push/disconnect routes. No network: a fake GraphQL transport is injected via
endear_sink._http_transport."""
import pytest
from fastapi.testclient import TestClient

from halia.adapters import endear_sink as es
from halia.api import shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.schema import ScoreResult
from halia.store import ShopStore


def res(cid="gid://shopify/Customer/123", email="vic@x.com", grade="A*", vic=True,
        signals=("Work email", "HNWI postcode")):
    return ScoreResult(matched=True, flagged=True, tier="A1", grade=grade, score=96,
                       is_priority=True, signal_count=len(signals), signals=list(signals),
                       reasons="; ".join(signals), gesture="", spend=420.0, hidden_vic=vic,
                       customer_id=cid, email=email, phone="+447700900123")


class FakeEndear:
    """Records every (query, variables); answers as Endear's GraphQL API would (200 + data)."""

    def __init__(self, fail_auth=False):
        self.calls = []
        self.fail_auth = fail_auth

    def __call__(self, query, variables=None):
        self.calls.append((query, variables or {}))
        if "currentBrand" in query:
            if self.fail_auth:
                return 200, {"errors": [{"message": "Missing or invalid api key",
                                         "extensions": {"code": "UNAUTHENTICATED"}}]}
            return 200, {"data": {"currentBrand": {"__typename": "Brand"}}}
        if "createCustomerField" in query:
            return 200, {"data": {"createCustomerField": {"__typename": "CustomerField"}}}
        if "bulkUpsertExternalCustomers" in query:
            return 200, {"data": {"bulkUpsertExternalCustomers": {"__typename": "Payload"}}}
        return 200, {"data": {}}


@pytest.fixture()
def fake(monkeypatch):
    f = FakeEndear()
    monkeypatch.setattr(es, "_http_transport", lambda key: f)
    return f


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "e.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    yield TestClient(app), store


def _tenant(store, shop="shope"):
    tok = new_token()
    store.create_tenant(shop, "woocommerce", "Shop", hash_token(tok))
    return tok


# ── sink ────────────────────────────────────────────────────────────────────────
def test_external_id_collapses_shopify_gid():
    assert es._external_id(res(cid="gid://shopify/Customer/123")) == "123"
    assert es._external_id(res(cid="wc_88")) == "wc_88"


def test_customer_input_carries_tags_and_custom_fields():
    ci = es._customer_input(res(grade="A*"))
    assert ci["id"] == "123" and ci["email_address"] == "vic@x.com"
    assert "Halia VIC" in ci["tags"] and "Halia: A*" in ci["tags"]
    fields = {f["key"]: f["values"] for f in ci["custom_fields"]}
    assert fields["halia_grade"] == ["A*"] and fields["halia_vic"] == ["Yes"]
    assert "Work email" in fields["halia_signals"][0]


def test_ensure_fields_defines_the_halia_fields(fake):
    es.EndearSink("key-x").ensure_fields()
    keys = {v.get("key") for (q, v) in fake.calls if "createCustomerField" in q}
    assert {"halia_grade", "halia_score", "halia_vic", "halia_signals"} <= keys


def test_ensure_fields_tolerates_already_exists(monkeypatch):
    class Dupes:
        def __call__(self, q, v=None):
            return 200, {"errors": [{"message": "A field with that key already exists"}]}
    monkeypatch.setattr(es, "_http_transport", lambda key: Dupes())
    es.EndearSink("key-x").ensure_fields()          # must not raise


def test_validate_key_rejects_unauthenticated(monkeypatch):
    monkeypatch.setattr(es, "_http_transport", lambda key: FakeEndear(fail_auth=True))
    with pytest.raises(es.EndearError):
        es.EndearSink("bad").validate_key()


def test_upsert_batches_and_counts(fake):
    n = es.EndearSink("key-x").push_many([res(cid="gid://shopify/Customer/1"),
                                          res(cid="gid://shopify/Customer/2")])
    assert n == 2
    up = next(v for (q, v) in fake.calls if "bulkUpsertExternalCustomers" in q)
    assert [c["id"] for c in up["customers"]] == ["1", "2"]


# ── routes ──────────────────────────────────────────────────────────────────────
def test_connect_status_disconnect(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    r = c.post("/v1/endear/connect", json={"api_key": "ek_abc"})
    assert r.status_code == 200 and r.json()["connected"] is True
    assert store.get_endear("shope")["api_key"] == "ek_abc"
    assert any("createCustomerField" in q for (q, v) in fake.calls)   # fields provisioned on connect
    assert c.get("/v1/endear/status").json()["connected"] is True
    assert c.post("/v1/endear/disconnect").json() == {"connected": False}
    assert store.get_endear("shope") is None


def test_connect_rejects_empty_key(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/endear/connect", json={"api_key": "  "}).status_code == 422


def test_push_hidden_vics(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    store.save_endear("shope", "ek_abc")
    cache.set("shope", [res()], {"data": []}, [])
    try:
        r = c.post("/v1/endear/push", json={})
        assert r.status_code == 200 and r.json()["pushed"] == 1
    finally:
        cache.evict("shope")


def test_push_requires_connection(client, fake):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    cache.set("shope", [res()], {"data": []}, [])
    try:
        assert c.post("/v1/endear/push", json={}).status_code == 400
    finally:
        cache.evict("shope")
