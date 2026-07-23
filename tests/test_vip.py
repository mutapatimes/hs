"""The VIP questionnaire: what this house offers, and the bounds it puts on the AI.

Two properties carry the feature. First, an unanswered questionnaire must cost nothing — most
merchants have never written a VIP policy down, and the product has to work before they do.
Second, and the reason it exists: the profile is a whitelist. A drafted reply that offers
complimentary alterations to a shop which does not alter is a promise an associate has to walk
back in front of a client, so nothing outside what the merchant ticked may reach the prompt.
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia import vip
from halia.api.app import app
from halia.store import ShopStore

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    store = ShopStore(db_path=tmp_path / "v.db")
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    yield TestClient(app), store


FULL = {"industry": "fashion", "services": ["styling", "alterations"],
        "appointments": "video", "perks": ["early_access", "after_hours"],
        "vip_offer": "we would open on a Sunday for her", "definition": "feel",
        "tone": "warm", "escalate": "anything over 2000, or a complaint"}


# ── nothing answered must cost nothing ────────────────────────────────────────
def test_an_unanswered_profile_adds_nothing_to_the_prompt():
    assert vip.house_block({}) == "" and vip.house_block(None) == ""
    assert vip.tone_line({}) == ""


def test_a_partial_answer_is_perfectly_valid():
    """Skipping is expected; one answer should still help."""
    block = vip.house_block({"services": ["engraving"]})
    assert "Engraving" in block and "Trade:" not in block


def test_going_by_feel_is_a_real_answer():
    assert "judge by feel" in vip.house_block({"definition": "feel"})


# ── the whitelist ─────────────────────────────────────────────────────────────
def test_the_block_forbids_offering_anything_unlisted():
    block = vip.house_block(FULL)
    assert "Offer only what is listed above" in block
    assert "never invent a service, a discount or a timeframe" in block


def test_only_what_they_ticked_reaches_the_prompt():
    block = vip.house_block({"services": ["styling"]})
    assert "Styling or personal shopping" in block
    assert "Alterations" not in block and "Engraving" not in block


def test_an_invented_service_cannot_be_posted_in():
    """A hand-posted payload must not widen what the AI may offer."""
    got = vip.clean_profile({"services": ["styling", "free_helicopter"], "tone": "shouty",
                             "industry": "not_a_trade", "nonsense": "x"})
    assert got == {"services": ["styling"]}
    assert "helicopter" not in vip.house_block(got).lower()


def test_free_text_is_kept_and_bounded():
    got = vip.clean_profile({"vip_offer": "x" * 900, "escalate": "  over 2k  "})
    assert len(got["vip_offer"]) == 600 and got["escalate"] == "over 2k"


def test_the_merchants_own_words_are_carried_through():
    assert 'we would open on a Sunday for her' in vip.house_block(FULL)


def test_escalation_reaches_the_prompt():
    assert "Hand to a person when: anything over 2000" in vip.house_block(FULL)


# ── tone ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tone,word", [("warm", "warm"), ("formal", "formal"),
                                       ("playful", "conversational"), ("discreet", "discreet")])
def test_each_tone_becomes_an_instruction(tone, word):
    assert word in vip.tone_line({"tone": tone})


# ── the definition is one source of truth ─────────────────────────────────────
def test_every_question_is_well_formed():
    keys = [q["key"] for q in vip.QUESTIONS]
    assert len(keys) == len(set(keys)) == 6
    for q in vip.QUESTIONS:
        assert q["type"] in ("one", "many") and q["title"] and q["options"]
        vals = [o["v"] for o in q["options"]]
        assert len(vals) == len(set(vals))
        assert all(o["l"] for o in q["options"])


def test_answered_counts_what_was_filled_in():
    assert vip.answered({}) == 0
    assert vip.answered(FULL) == len(FULL)


# ── the endpoint + settings round-trip ────────────────────────────────────────
def test_questions_are_served_with_any_existing_answers(client):
    c, _ = client
    d = c.get("/v1/vip/questions", headers=_auth()).json()
    assert len(d["questions"]) == 6 and d["profile"] == {}
    assert d["questions"][0]["key"] == "industry"


def test_the_profile_saves_and_reloads(client):
    c, _ = client
    c.post("/v1/settings", headers=_auth(), json={"vic_threshold": 5000, "vip_profile": FULL})
    assert c.get("/v1/settings", headers=_auth()).json()["vip_profile"]["tone"] == "warm"
    assert c.get("/v1/vip/questions", headers=_auth()).json()["profile"]["industry"] == "fashion"


def test_saving_other_settings_does_not_wipe_the_profile(client):
    """The Settings form does not send vip_profile, and must not clear it."""
    c, _ = client
    c.post("/v1/settings", headers=_auth(), json={"vic_threshold": 5000, "vip_profile": FULL})
    c.post("/v1/settings", headers=_auth(), json={"vic_threshold": 8000, "sender_name": "The Team"})
    kept = c.get("/v1/settings", headers=_auth()).json()
    assert kept["vip_profile"]["tone"] == "warm" and kept["vic_threshold"] == 8000


def test_a_junk_profile_is_cleaned_on_save(client):
    c, _ = client
    c.post("/v1/settings", headers=_auth(),
           json={"vic_threshold": 5000, "vip_profile": {"services": ["styling", "made_up"]}})
    assert c.get("/v1/settings", headers=_auth()).json()["vip_profile"] == {"services": ["styling"]}
