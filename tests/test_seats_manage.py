"""Settings → Team: edit a teammate's details and re-issue their sign-in from the dashboard."""
import pytest
from fastapi.testclient import TestClient

from halia import journeys, notify_brevo
from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "team.myshopify.com"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "t.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    monkeypatch.setattr(journeys, "enroll_associate", lambda *a, **k: True)
    monkeypatch.setattr(notify_brevo, "add_associate", lambda *a, **k: True)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison Test", hash_token(tok))
    client = TestClient(app)
    seat = client.post("/v1/seats", json={"name": "Sarah Bloom", "email": "sarah@maison.com"},
                       cookies={COOKIE: tok}).json()
    yield client, store, tok, seat


def test_edit_name_email_position_signoff(env):
    client, store, tok, seat = env
    r = client.patch(f"/v1/seats/{seat['seat_id']}", cookies={COOKIE: tok},
                     json={"name": "Sarah B.", "email": "SB@maison.com", "title": "Client Advisor", "signoff": "Warmly, Sarah"})
    assert r.status_code == 200, r.text
    listed = client.get("/v1/seats", cookies={COOKIE: tok}).json()["seats"][0]
    assert listed["name"] == "Sarah B." and listed["email"] == "sb@maison.com"
    assert listed["title"] == "Client Advisor" and listed["signoff"] == "Warmly, Sarah"


def test_edit_refuses_a_taken_email_and_unknown_seat(env):
    client, store, tok, seat = env
    client.post("/v1/seats", json={"name": "Tom", "email": "tom@maison.com"}, cookies={COOKIE: tok})
    r = client.patch(f"/v1/seats/{seat['seat_id']}", json={"email": "tom@maison.com"}, cookies={COOKIE: tok})
    assert r.status_code == 409
    assert client.patch("/v1/seats/nope", json={"name": "x"}, cookies={COOKIE: tok}).status_code == 404


def test_reissue_returns_a_fresh_token_and_kills_the_old(env):
    client, store, tok, seat = env
    r = client.post(f"/v1/seats/{seat['seat_id']}/reissue", cookies={COOKIE: tok})
    d = r.json()
    assert r.status_code == 200 and d["token"] != seat["token"] and d["reissued"] is True
    assert d["connect"].startswith("halia://connect?t=") and d["name"] == "Sarah Bloom"
    assert store.seat_for_token(hash_token(d["token"]))["seat_id"] == seat["seat_id"]
    assert store.seat_for_token(hash_token(seat["token"])) is None
    # still one seat, not a twin
    assert len(client.get("/v1/seats", cookies={COOKIE: tok}).json()["seats"]) == 1
