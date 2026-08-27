"""The associate's profile lives on their seat: drafts, templates and the team see the same
name, position and sign-off, edited from the extension or the iPhone app."""
import pytest
from fastapi.testclient import TestClient

from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.extension import ExtAuth, _draft_context, _seat_profile
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "profile.myshopify.com"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "p.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison Test", hash_token(tok))
    seat_tok = new_token()
    seat_id = store.create_seat(SHOP, "Sarah Bloom", hash_token(seat_tok), "sarah@maison.com")
    shared = new_token()
    store.set_extension_token(SHOP, hash_token(shared))
    yield TestClient(app), store, tok, seat_tok, seat_id, shared


def _h(t):
    return {"X-Halia-Ext-Token": t}


def test_profile_round_trip_and_default_signoff(env):
    client, store, tok, seat_tok, seat_id, _ = env
    p = client.get("/v1/extension/profile", headers=_h(seat_tok)).json()["profile"]
    assert p["name"] == "Sarah Bloom" and p["default_signoff"] is True
    assert p["signoff"] == "Sarah Bloom\nMaison Test"
    r = client.post("/v1/extension/profile", headers=_h(seat_tok),
                    json={"title": "Client Advisor", "signoff": ""})
    p = r.json()["profile"]
    assert p["title"] == "Client Advisor" and p["signoff"] == "Sarah Bloom\nClient Advisor, Maison Test"
    r = client.post("/v1/extension/profile", headers=_h(seat_tok),
                    json={"signoff": "Warm regards,\nSarah"})
    assert r.json()["profile"]["signoff"] == "Warm regards,\nSarah"
    assert r.json()["profile"]["default_signoff"] is False


def test_email_stays_unique_and_shared_token_cannot_edit(env):
    client, store, tok, seat_tok, seat_id, shared = env
    store.create_seat(SHOP, "Omar", hash_token(new_token()), "omar@maison.com")
    r = client.post("/v1/extension/profile", headers=_h(seat_tok), json={"email": "omar@maison.com"})
    assert r.status_code == 409
    r = client.post("/v1/extension/profile", headers=_h(seat_tok), json={"email": "nope"})
    assert r.status_code == 422
    r = client.post("/v1/extension/profile", headers=_h(shared), json={"title": "x"})
    assert r.status_code == 400


def test_context_and_templates_sign_as_the_seat(env):
    client, store, tok, seat_tok, seat_id, shared = env
    client.post("/v1/settings", json={"vic_threshold": 500, "sender_name": "The Maison team",
                "email_templates": [{"category": "Welcome", "name": "Hello", "subject": "Hi",
                                     "body": "Dear {first_name},\nWelcome.\n{sender}"}]},
                cookies={COOKIE: tok})
    client.post("/v1/extension/profile", headers=_h(seat_tok), json={"title": "Client Advisor"})
    d = client.get("/v1/extension/context", headers=_h(seat_tok)).json()
    assert d["profile"]["title"] == "Client Advisor"
    assert "Sarah Bloom\nClient Advisor, Maison Test" in d["templates"][0]["body"]
    # a shared-token install still signs with the store sender
    d2 = client.get("/v1/extension/context", headers=_h(shared)).json()
    assert "The Maison team" in d2["templates"][0]["body"]


def test_draft_prompt_signs_off_as_the_seat(env):
    client, store, tok, seat_tok, seat_id, _ = env
    store.update_seat_profile(seat_id, title="Client Advisor", signoff="Warm regards,\nSarah")
    auth = ExtAuth(shop=SHOP, seat_id=seat_id, seat_name="Sarah Bloom")
    ctx = _draft_context(SHOP, {"found": False}, "whatsapp", [], "", writer=_seat_profile(auth))
    assert "You are writing as: Sarah Bloom, Client Advisor" in ctx
    assert "Sign off exactly as:\nWarm regards,\nSarah" in ctx
