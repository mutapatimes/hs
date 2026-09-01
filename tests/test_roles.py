"""Managers and associates: who set the store up, and who works the floor."""
import json

import jwt
import pytest
from fastapi.testclient import TestClient

from halia import config
from halia.api import onboarding, roles, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "maison.myshopify.com"
SECRET = "sekret-for-sessions"
KEY = "api-key-1"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "r.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    monkeypatch.setattr(config, "SHOPIFY_API_SECRET", SECRET)
    monkeypatch.setattr(config, "SHOPIFY_API_KEY", KEY)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(tok))
    yield TestClient(app), store, tok


def _session(sub: str) -> str:
    """An App Bridge session token for one logged-in Shopify staff member."""
    import time
    return jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}",
                       "aud": KEY, "sub": sub, "exp": int(time.time()) + 600,
                       "nbf": int(time.time()) - 10, "iat": int(time.time())},
                      SECRET, algorithm="HS256")


def _hdr(sub: str) -> dict:
    return {"Authorization": "Bearer " + _session(sub)}


def test_the_first_staff_member_through_the_door_owns_the_store(env):
    client, store, _ = env
    assert roles.owner_staff_id(SHOP) == ""
    r = client.get("/v1/seats", headers=_hdr("111"))
    assert r.status_code == 200 and r.json()["role"] == "manager"
    assert roles.owner_staff_id(SHOP) == "111"
    # and they keep it: a second person does not take it over
    assert client.get("/v1/seats", headers=_hdr("222")).json()["role"] == "associate"
    assert roles.owner_staff_id(SHOP) == "111"


def test_an_associate_cannot_change_what_the_whole_store_sees(env):
    client, store, _ = env
    client.get("/v1/seats", headers=_hdr("111"))          # the owner sets the store up
    them = _hdr("222")
    for path, body in (("/v1/settings", {"vic_threshold": 1}),
                       ("/v1/seats", {"name": "Ella"}),
                       ("/v1/checkout", None)):
        r = client.post(path, json=body, headers=them)
        assert r.status_code == 403, (path, r.status_code)
        assert "manager" in r.json()["detail"]
    # reading is not the same as changing: the floor still needs the settings and the team
    assert client.get("/v1/settings", headers=them).status_code == 200
    assert client.get("/v1/seats", headers=them).status_code == 200


def test_a_manager_lets_a_shopify_staff_member_in_and_can_promote_them(env):
    client, store, _ = env
    boss = _hdr("111")
    client.get("/v1/seats", headers=boss)
    client.get("/v1/seats", headers=_hdr("222"))          # a new hire opens the app
    assert [p["id"] for p in client.get("/v1/seats", headers=boss).json()["pending"]] == ["222"]
    r = client.post("/v1/seats/grant", json={"staff_id": "222", "name": "Ella Rowe"}, headers=boss)
    assert r.status_code == 200 and r.json()["role"] == "associate"
    d = client.get("/v1/seats", headers=boss).json()
    assert d["pending"] == [] and [s["name"] for s in d["seats"]] == ["Ella Rowe"]
    assert d["seats"][0]["role"] == "associate" and d["seats"][0]["shopifyUser"] is True
    # they are recognised by their Shopify account, with no token to hand over
    assert client.get("/v1/seats", headers=_hdr("222")).json()["role"] == "associate"
    assert client.post("/v1/settings", json={"vic_threshold": 1}, headers=_hdr("222")).status_code == 403
    # promoted, they can
    seat_id = d["seats"][0]["id"]
    assert client.post(f"/v1/seats/{seat_id}/role", json={"role": "manager"}, headers=boss).status_code == 200
    assert client.get("/v1/seats", headers=_hdr("222")).json()["role"] == "manager"
    assert client.post("/v1/settings", json={"vic_threshold": 1}, headers=_hdr("222")).status_code == 200
    # and an associate can never promote themselves
    client.post(f"/v1/seats/{seat_id}/role", json={"role": "associate"}, headers=boss)
    assert client.post(f"/v1/seats/{seat_id}/role", json={"role": "manager"},
                       headers=_hdr("222")).status_code == 403


def test_a_manager_can_revoke_someone(env):
    client, store, _ = env
    boss = _hdr("111")
    client.get("/v1/seats", headers=boss)
    client.post("/v1/seats/grant", json={"staff_id": "222", "name": "Ella"}, headers=boss)
    seat_id = client.get("/v1/seats", headers=boss).json()["seats"][0]["id"]
    assert client.post(f"/v1/seats/{seat_id}/revoke", headers=boss).status_code == 200
    assert client.get("/v1/seats", headers=boss).json()["seats"] == []
    # revoked, they are a stranger again rather than an associate with a live seat
    assert store.seat_by_staff_id(SHOP, "222") is None


def test_the_private_link_is_always_the_manager(env):
    # WooCommerce and the hosted dashboard sign in with the secret link itself: there is no Shopify
    # staff account to read, and the holder of the link is the merchant.
    client, store, tok = env
    c = TestClient(app, cookies={COOKIE: tok})
    assert c.get("/v1/seats").json()["role"] == "manager"
    assert c.post("/v1/settings", json={"vic_threshold": 1}).status_code == 200


def test_the_house_voice_is_a_managers_to_move(env):
    client, store, _ = env
    client.get("/v1/seats", headers=_hdr("111"))
    boss_tok, floor_tok = new_token(), new_token()
    store.create_seat(SHOP, "Sarah", hash_token(boss_tok), "sarah@m.com", role="manager")
    store.create_seat(SHOP, "Ella", hash_token(floor_tok), "ella@m.com")
    body = {"voice": {"formality": 10, "exclusivity": 10, "attentiveness": 10,
                      "polish": 10, "language": "en"}}
    floor = {"X-Halia-Ext-Token": floor_tok}
    assert client.get("/v1/extension/voice", headers=floor).json()["can_edit"] is False
    assert client.post("/v1/extension/voice", json=body, headers=floor).status_code == 403
    boss = {"X-Halia-Ext-Token": boss_tok}
    assert client.get("/v1/extension/voice", headers=boss).json()["can_edit"] is True
    assert client.post("/v1/extension/voice", json=body, headers=boss).status_code == 200
    assert json.loads(store.get_settings_raw(SHOP))["voice"]["formality"] == 10
