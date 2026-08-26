"""The house voice: sliders + language, instant sample, model-backed preview/rewrite, and the
voice riding every draft."""
import json

import pytest
from fastapi.testclient import TestClient

from halia import voice as V
from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "shopx"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "v.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "woocommerce", "Shop X", hash_token(tok))
    yield TestClient(app), store, tok


def test_clean_voice_clamps_and_defaults():
    v = V.clean_voice({"formality": 250, "exclusivity": -4, "polish": "x", "language": "klingon"})
    assert v["formality"] == 100 and v["exclusivity"] == 0
    assert v["polish"] == V.DEFAULT_VOICE["polish"] and v["language"] == "en"
    assert V.clean_voice(None) == V.DEFAULT_VOICE


def test_sample_moves_with_the_sliders():
    relaxed = V.sample_message({k: 5 for k in V.AXES})
    formal = V.sample_message({k: 95 for k in V.AXES})
    assert relaxed != formal
    assert relaxed.startswith("Hi Charlotte") and formal.startswith("Dear Charlotte")
    assert "private view" in formal and "Come by whenever" in relaxed
    assert "Sarah" in relaxed and "Sarah" in formal          # sender always signs


def test_brief_names_the_language_and_bands():
    b = V.voice_brief({"formality": 90, "exclusivity": 10, "language": "fr"})
    assert "French" in b and "formal" in b and "welcoming and open" in b


def test_settings_round_trip(env):
    client, store, tok = env
    r = client.post("/v1/settings", json={"vic_threshold": 500,
                                          "voice": {"formality": 20, "language": "it"}},
                    cookies={COOKIE: tok})
    assert r.status_code == 200
    got = client.get("/v1/settings", cookies={COOKIE: tok}).json()["voice"]
    assert got["formality"] == 20 and got["language"] == "it"
    # a later save without the voice keeps it
    client.post("/v1/settings", json={"vic_threshold": 600}, cookies={COOKIE: tok})
    assert json.loads(store.get_settings_raw(SHOP))["voice"]["language"] == "it"


def test_preview_is_instant_without_ai(env, monkeypatch):
    client, _, tok = env
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    r = client.post("/v1/voice/preview", json={"voice": {"formality": 90}, "ai": True},
                    cookies={COOKIE: tok})
    d = r.json()
    assert r.status_code == 200 and d["sample"].startswith("Dear Charlotte")
    assert "ai" not in d and d["ai_available"] is False


def test_rewrite_needs_ai_and_keeps_placeholders(env, monkeypatch):
    client, _, tok = env
    from halia import llm
    from halia.api import voice as voice_api
    monkeypatch.setattr(llm, "available", lambda: False)
    r = client.post("/v1/voice/rewrite", json={"voice": {}}, cookies={COOKIE: tok})
    assert r.status_code == 409
    # with a model: proposals come back merged onto the originals, names untouched
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: {"templates": [
        {"name": "Personal welcome", "subject": "Une note", "body": "Chère {first_name}, ... {sender}"}]})
    tpls = [{"category": "Welcome", "name": "Personal welcome", "subject": "A note",
             "body": "Dear {first_name}, ... {sender}"}]
    r = client.post("/v1/voice/rewrite", json={"voice": {"language": "fr"}, "templates": tpls},
                    cookies={COOKIE: tok})
    d = r.json()
    assert r.status_code == 200 and d["count"] == 1
    assert d["templates"][0]["category"] == "Welcome"
    assert "{first_name}" in d["templates"][0]["body"] and d["templates"][0]["subject"] == "Une note"


def test_draft_context_carries_the_voice(env):
    client, store, tok = env
    from halia.api.extension import _draft_context
    client.post("/v1/settings", json={"vic_threshold": 500, "voice": {"language": "de",
                "exclusivity": 95}}, cookies={COOKIE: tok})
    ctx = _draft_context(SHOP, {"found": False}, "whatsapp", [], "")
    assert "write in German" in ctx and "discreetly exclusive" in ctx
