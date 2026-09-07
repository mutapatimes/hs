"""The decks (/pitch, /present, /present-brands) are password-gated and never indexed."""
import pytest
from fastapi.testclient import TestClient

from halia.api.app import app

client = TestClient(app)
DECKS = ["/pitch", "/present", "/present-brands"]
PW = "letsmakelotsofmoneythisyear"


@pytest.mark.parametrize("path", DECKS)
def test_gate_shown_without_password(path):
    r = client.get(path)
    assert r.status_code == 200
    assert "This briefing is private" in r.text
    assert "Halia score" not in r.text                       # no deck content leaks past the gate
    assert r.headers.get("x-robots-tag") == "noindex, nofollow"


def test_wrong_password_is_declined():
    r = client.post("/pitch", data={"pw": "guess"})
    assert r.status_code == 401
    assert "declined" in r.text
    assert r.headers.get("x-robots-tag") == "noindex, nofollow"


@pytest.mark.parametrize("path", DECKS)
def test_right_password_unlocks_all_decks(path):
    c = TestClient(app)
    r = c.post(path, data={"pw": PW}, follow_redirects=False)
    assert r.status_code == 303 and "halia_deck" in r.headers.get("set-cookie", "")
    r2 = c.get(path)                                          # cookie carries across requests
    assert r2.status_code == 200
    assert "Halia score" in r2.text or "slide" in r2.text     # the real deck
    assert 'name="robots" content="noindex' in r2.text
    assert r2.headers.get("x-robots-tag") == "noindex, nofollow"


def test_one_password_opens_every_deck():
    c = TestClient(app)
    c.post("/pitch", data={"pw": PW}, follow_redirects=False)
    for path in DECKS:
        assert "This briefing is private" not in c.get(path).text


def test_forged_cookie_is_rejected():
    c = TestClient(app)
    c.cookies.set("halia_deck", "deadbeef" * 5)
    assert "This briefing is private" in c.get("/pitch").text


def test_decks_stay_out_of_the_sitemap():
    xml = client.get("/sitemap.xml").text
    for path in DECKS:
        assert path not in xml


def test_token_link_grants_access_without_the_password():
    from halia.api.app import _deck_token
    c = TestClient(app)
    r = c.get(f"/pitch?k={_deck_token()}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pitch"
    assert "halia_deck" in r.headers.get("set-cookie", "")
    assert "This briefing is private" not in c.get("/pitch").text


def test_wrong_token_stays_at_the_gate():
    c = TestClient(app)
    r = c.get("/pitch?k=not-the-token")
    assert "This briefing is private" in r.text


def test_password_entry_lands_on_the_shareable_link():
    from halia.api.app import _deck_password, _deck_token
    c = TestClient(app)
    r = c.post("/present", data={"pw": _deck_password()}, follow_redirects=False)
    assert r.headers["location"] == f"/present?k={_deck_token()}"
