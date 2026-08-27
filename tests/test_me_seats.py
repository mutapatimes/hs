"""The dashboard knows who is acting: a Shopify staff user maps to a seat once, hosted browsers
keep their chosen seat, and pipeline logs / assignments carry the seat without asking."""
import json

import pytest
from fastapi.testclient import TestClient

from halia.api import board, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "me.myshopify.com"


class FakeSink:
    def __init__(self):
        self.meta, self.tags = {}, {}
    def get_metafield(self, cid, key): return self.meta.get((cid, key))
    def set_metafield(self, cid, key, value): self.meta[(cid, key)] = value
    def write_metafield(self, cid, key, value): self.meta[(cid, key)] = value
    def tag_customer(self, cid, tags): self.tags.setdefault(cid, set()).update(tags)
    def untag_customer(self, cid, tags): self.tags.setdefault(cid, set()).difference_update(tags)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "m.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(tok))
    sarah = store.create_seat(SHOP, "Sarah Bloom", hash_token(new_token()), "sarah@maison.com")
    omar = store.create_seat(SHOP, "Omar Haddad", hash_token(new_token()), "omar@maison.com")
    sink = FakeSink()
    monkeypatch.setattr(board, "_sink", lambda shop: sink)
    monkeypatch.setattr(board, "_write_soft", lambda sink_, cid, pipe: None)
    client = TestClient(app, cookies={COOKIE: tok})
    yield client, store, sarah, omar, sink, monkeypatch


def test_staff_user_is_remembered_as_a_seat(env):
    client, store, sarah, omar, sink, mp = env
    mp.setattr(board, "current_staff_id", lambda request: "staff-42")
    d = client.get("/v1/me").json()
    assert d["staff_id"] == "staff-42" and d["seat"] is None and len(d["seats"]) == 2
    assert client.post("/v1/me", json={"seat_id": sarah}).json()["remembered"] is True
    assert client.get("/v1/me").json()["seat"]["name"] == "Sarah Bloom"
    # from now on every pipeline action is attributed without an actor in the payload
    r = client.post("/v1/board/note", json={"cid": "c1", "note": "Called about the coat"})
    assert r.status_code == 200
    act = r.json()["pipeline"]["activity"][-1]
    assert act["actor_id"] == sarah and act["actor_name"] == "Sarah Bloom"


def test_hosted_browser_passes_its_seat(env):
    client, store, sarah, omar, sink, mp = env
    mp.setattr(board, "current_staff_id", lambda request: None)
    assert client.get("/v1/me?seat_id=" + omar).json()["seat"]["name"] == "Omar Haddad"
    r = client.post("/v1/board/note", json={"cid": "c2", "note": "hi", "seat_id": omar})
    act = r.json()["pipeline"]["activity"][-1]
    assert act["actor_id"] == omar and act["actor_name"] == "Omar Haddad"
    # a seat from another shop is ignored, falling back to the typed name
    r = client.post("/v1/board/note", json={"cid": "c3", "note": "hi", "seat_id": "nope", "actor": "Typed"})
    assert r.json()["pipeline"]["activity"][-1]["actor_name"] == "Typed"


def test_assign_by_seat_fills_id_and_name(env):
    client, store, sarah, omar, sink, mp = env
    mp.setattr(board, "current_staff_id", lambda request: None)
    r = client.post("/v1/board/assign", json={"cid": "c1", "assignee_seat": omar, "seat_id": sarah})
    assert r.status_code == 200
    p = r.json()["pipeline"]
    assert p["assignee"] == {"id": omar, "name": "Omar Haddad"}
    assert p["activity"][-1]["action"] == "assigned:Omar Haddad" and p["activity"][-1]["actor_id"] == sarah
    assert client.post("/v1/board/assign", json={"cid": "c1", "assignee_seat": "ghost"}).status_code == 422
    bad = client.post("/v1/me", json={"seat_id": "ghost"})
    assert bad.status_code == 422
