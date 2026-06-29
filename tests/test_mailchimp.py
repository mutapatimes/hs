"""Mailchimp sink + per-shop integration endpoints (no network: injected transport)."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from halia.adapters import mailchimp_sink as ms
from halia.api import shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.schema import ScoreResult
from halia.store import ShopStore


def res(email="a@b.com", grade="A*", vic=True, signals=("Work email", "HNWI postcode")):
    return ScoreResult(matched=True, flagged=True, tier="A1", grade=grade, score=96,
                       is_priority=True, signal_count=len(signals), signals=list(signals),
                       reasons="; ".join(signals), gesture="", spend=420.0, hidden_vic=vic,
                       customer_id="c1", email=email, phone=None)


# ── sink ────────────────────────────────────────────────────────────────────────
def test_dc_and_subscriber_hash():
    assert ms.dc_from_key("abc123-us21") == "us21"
    with pytest.raises(ms.MailchimpError):
        ms.dc_from_key("nokey")  # no '-<dc>' suffix
    assert ms.subscriber_hash("A@B.com") == hashlib.md5(b"a@b.com").hexdigest()


def test_push_one_upserts_member_then_tags():
    calls = []

    def transport(method, path, body=None):
        calls.append((method, path, body))
        return 200, {"id": "m1"}

    ms.MailchimpSink("k-us1", "L", transport=transport).push_one(res(), scored_at="2026-01-01T00:00:00")
    h = ms.subscriber_hash("a@b.com")
    put = [b for m, p, b in calls if m == "PUT" and p == f"/lists/L/members/{h}"]
    assert put and put[0]["status_if_new"] == "transactional"
    assert put[0]["merge_fields"]["HGRADE"] == "A*" and put[0]["merge_fields"]["HVIC"] == "Yes"
    tags = [b for m, p, b in calls if m == "POST" and p.endswith("/tags")][0]
    names = {t["name"] for t in tags["tags"]}
    assert {"Halia A*", "Halia Hidden VIC", "Halia: Work email"} <= names


def test_push_many_counts_only_emailable():
    cnt = ms.MailchimpSink("k-us1", "L", transport=lambda m, p, b=None: (200, {})).push_many(
        [res("x@y.com"), res(None), res("z@y.com")])
    assert cnt == 2


# ── endpoints ─────────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "m.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    yield TestClient(app), store


def _tenant(store, shop="shopm"):
    tok = new_token()
    store.create_tenant(shop, "woocommerce", "Shop", hash_token(tok))
    return tok


def test_connect_status_disconnect(client, monkeypatch):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    monkeypatch.setattr(ms, "list_audiences", lambda key, transport=None: [{"id": "aud1", "name": "Main list"}])
    monkeypatch.setattr(ms.MailchimpSink, "ensure_merge_fields", lambda self: None)

    r = c.post("/v1/mailchimp/connect", json={"api_key": "abc123-us21"})
    assert r.status_code == 200 and r.json()["list_name"] == "Main list"
    assert store.get_mailchimp("shopm")["list_id"] == "aud1"
    assert c.get("/v1/mailchimp/status").json() == {"connected": True, "list_name": "Main list"}

    assert c.post("/v1/mailchimp/disconnect").status_code == 200
    assert store.get_mailchimp("shopm") is None


def test_connect_rejects_bad_key(client):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    assert c.post("/v1/mailchimp/connect", json={"api_key": "nodatacenter"}).status_code == 422


def test_push_hidden_vics(client, monkeypatch):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    store.save_mailchimp("shopm", "abc123-us21", "aud1", "Main list")
    cache.set("shopm", [res("vic@x.com")], {"data": []}, [])
    monkeypatch.setattr(ms.MailchimpSink, "push_many", lambda self, targets: len(list(targets)))

    r = c.post("/v1/mailchimp/push", json={})
    assert r.status_code == 200 and r.json()["pushed"] == 1 and r.json()["list_name"] == "Main list"


def test_push_requires_connection(client):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    cache.set("shopm", [res()], {"data": []}, [])
    assert c.post("/v1/mailchimp/push", json={}).status_code == 400
