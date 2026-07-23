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


FULL = {"industry": "fashion", "products": ["womenswear", "shoes"],
        "services": ["styling", "alterations"],
        "terms": {"styling": "free", "alterations": "vip"},
        "perks": ["early_access", "after_hours"],
        "vip_offer": "we would open on a Sunday for her", "definition": "feel",
        "tone": "warm"}


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
    assert "never invent a service, a price or a timeframe" in block


def test_only_what_they_ticked_reaches_the_prompt():
    block = vip.house_block({"services": ["styling"]})
    assert "Styling or personal shopping" in block
    assert "Alterations" not in block and "Engraving" not in block


def test_what_they_sell_reaches_the_prompt():
    assert "Sells: Womenswear, Shoes" in vip.house_block(FULL)


def test_an_invented_service_cannot_be_posted_in():
    """A hand-posted payload must not widen what the AI may offer."""
    got = vip.clean_profile({"services": ["styling", "free_helicopter"], "tone": "shouty",
                             "industry": "not_a_trade", "products": ["moon_rocks"], "nonsense": "x"})
    assert got == {"services": ["styling"]}
    assert "helicopter" not in vip.house_block(got).lower()


def test_free_text_is_kept_and_bounded():
    got = vip.clean_profile({"vip_offer": "  " + "x" * 900 + "  "})
    assert len(got["vip_offer"]) == 600


def test_the_merchants_own_words_are_carried_through():
    assert 'we would open on a Sunday for her' in vip.house_block(FULL)


def test_there_is_no_escalation_question():
    """Halia never sends anything, so a conversation is always with a person. Asking when to hand
    over would imply an autonomy the product does not have."""
    assert all("escalate" not in (q.get("free") or "") for q in vip.QUESTIONS)
    assert "Hand to a person" not in vip.house_block(FULL)
    assert vip.clean_profile({"escalate": "over 2k"}) == {}


# ── tone ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tone,word", [("warm", "warm"), ("formal", "formal"),
                                       ("playful", "conversational"), ("discreet", "discreet")])
def test_each_tone_becomes_an_instruction(tone, word):
    assert word in vip.tone_line({"tone": tone})


# ── the definition is one source of truth ─────────────────────────────────────
def test_every_question_is_well_formed():
    keys = [q["key"] for q in vip.QUESTIONS]
    assert len(keys) == len(set(keys)) == 7
    for q in vip.QUESTIONS:
        assert q["type"] in ("one", "many", "terms") and q["title"]
        if q["type"] == "terms":
            continue
        assert q.get("options") or q.get("by_industry")
        for opts in ([q["options"]] if q.get("options") else
                     list(vip._POOLS[q["by_industry"]].values())):
            vals = [o["v"] for o in opts]
            assert len(vals) == len(set(vals)) and all(o["l"] for o in opts)


# ── the questions branch on what they sell ────────────────────────────────────
def test_each_trade_is_asked_in_its_own_words():
    jewel = {o["l"] for o in vip.options_for("services", "jewellery")}
    fash = {o["l"] for o in vip.options_for("services", "fashion")}
    assert "Resizing" in jewel and "Restringing" in jewel
    assert "Resizing" not in fash and "Alterations & tailoring" in fash
    assert {o["l"] for o in vip.options_for("products", "jewellery")} >= {"Watches", "Fine jewellery"}


def test_common_services_are_offered_to_every_trade():
    for trade in vip.SERVICES:
        labels = {o["l"] for o in vip.options_for("services", trade)}
        assert "Gift wrapping & personalisation" in labels
        assert "Private appointments" in labels


def test_products_carry_no_common_tail():
    """Only services are shared across trades; nobody sells a generic product."""
    assert {o["v"] for o in vip.options_for("products", "food")} == \
        {o["v"] for o in vip.PRODUCTS["food"]}


def test_an_unknown_trade_simply_has_nothing_to_ask():
    assert vip.options_for("products", "not_a_trade") == []


# ── how a service is charged for ──────────────────────────────────────────────
def test_terms_reach_the_prompt_in_words():
    block = vip.house_block({"industry": "jewellery", "services": ["polishing", "resizing", "engraving"],
                             "terms": {"polishing": "free", "resizing": "paid", "engraving": "vip"}})
    assert "Polishing & cleaning (complimentary)" in block
    assert "Resizing (chargeable)" in block
    assert "Engraving (complimentary for a top client, chargeable otherwise)" in block


def test_the_prompt_forbids_calling_a_charged_service_free():
    block = vip.house_block({"services": ["resizing"], "terms": {"resizing": "paid"}})
    assert "Never describe a chargeable service as free" in block


def test_terms_for_a_service_they_do_not_offer_are_dropped():
    """Otherwise a stale term could make an unoffered service look available."""
    got = vip.clean_profile({"services": ["polishing"],
                             "terms": {"polishing": "free", "resizing": "free"}})
    assert got["terms"] == {"polishing": "free"}


def test_an_invented_term_is_dropped():
    got = vip.clean_profile({"services": ["polishing"], "terms": {"polishing": "half_price"}})
    assert "terms" not in got


def test_a_service_with_no_term_still_lists_plainly():
    block = vip.house_block({"services": ["polishing"]})
    assert "Polishing & cleaning" in block and "(" not in block.split("Services they offer:")[1].split("\n")[0]


def test_answered_counts_what_was_filled_in():
    assert vip.answered({}) == 0
    assert vip.answered(FULL) == len(FULL)


# ── the endpoint + settings round-trip ────────────────────────────────────────
def test_questions_are_served_with_any_existing_answers(client):
    c, _ = client
    d = c.get("/v1/vip/questions", headers=_auth()).json()
    assert len(d["questions"]) == 7 and d["profile"] == {}
    assert d["questions"][0]["key"] == "industry"
    # the per-trade pools travel with the questions, so step 1 can re-point steps 2 and 3
    assert "jewellery" in d["services"] and "jewellery" in d["products"]
    assert {t["v"] for t in d["terms"]} == {"free", "vip", "paid"}


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
