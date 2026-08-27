"""Seats are identified by email: one live seat per email per shop, re-issue instead of twins,
and a new seat starts the associate onboarding journey."""
import pytest
from fastapi.testclient import TestClient

from halia import emails, journeys, notify_brevo
from halia.api import onboarding, seats as seats_api, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "team.myshopify.com"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "t.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Maison Test", hash_token(tok))
    enrolled, brevo = [], []
    monkeypatch.setattr(journeys, "enroll_associate", lambda email, **kw: enrolled.append((email, kw)) or True)
    monkeypatch.setattr(notify_brevo, "add_associate", lambda email, attrs=None: brevo.append(email) or True)
    yield TestClient(app), store, tok, enrolled, brevo


def _post(client, tok, body):
    return client.post("/v1/seats", json=body, cookies={COOKIE: tok})


def test_new_seat_by_email_starts_the_journey(env):
    client, store, tok, enrolled, brevo = env
    r = _post(client, tok, {"name": "Sarah Bloom", "email": "Sarah@Maison.com"})
    d = r.json()
    assert r.status_code == 200 and d["email"] == "sarah@maison.com" and d["reissued"] is False
    assert store.seat_for_token(hash_token(d["token"]))["seat_id"] == d["seat_id"]
    assert enrolled and enrolled[0][0] == "sarah@maison.com"
    assert enrolled[0][1]["first"] == "Sarah" and enrolled[0][1]["store_name"] == "Maison Test"
    assert enrolled[0][1]["connect"].startswith("halia://connect?t=")
    assert brevo == ["sarah@maison.com"]
    listed = client.get("/v1/seats", cookies={COOKIE: tok}).json()["seats"]
    assert listed[0]["email"] == "sarah@maison.com"


def test_same_email_reissues_the_seat(env):
    client, store, tok, enrolled, brevo = env
    first = _post(client, tok, {"name": "Sarah", "email": "sarah@maison.com"}).json()
    again = _post(client, tok, {"name": "Sarah B", "email": "sarah@maison.com"}).json()
    assert again["reissued"] is True and again["seat_id"] == first["seat_id"]
    assert again["token"] != first["token"]
    assert store.seat_for_token(hash_token(first["token"])) is None        # old token dead
    assert store.seat_for_token(hash_token(again["token"]))["name"] == "Sarah B"
    assert len(enrolled) == 1 and len(brevo) == 1                          # journey only once
    assert len(client.get("/v1/seats", cookies={COOKIE: tok}).json()["seats"]) == 1


def test_bad_email_rejected_and_nameless_browser_seat_still_works(env):
    client, store, tok, enrolled, _ = env
    assert _post(client, tok, {"name": "X", "email": "not-an-email"}).status_code == 422
    r = _post(client, tok, {"name": "Manager's browser"})
    assert r.status_code == 200 and r.json()["email"] == "" and enrolled == []


def test_welcome_email_carries_the_sign_in_link():
    subject, html, text = emails.render("assoc_welcome", {
        "first": "Sarah", "store_name": "Maison Test", "connect": "halia://connect?t=abc&b=https://x"},
        "https://x/u")
    assert "Maison Test" in subject and "halia://connect?t=abc" in html and "halia://connect" in text
    for key in ("assoc_first_moves", "assoc_capture", "assoc_habits"):
        s2, h2, t2 = emails.render(key, {"first": "Sarah"}, "https://x/u")
        assert s2 and h2 and t2
