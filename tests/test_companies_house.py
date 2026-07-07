"""Companies House control signal: matching, tiering + corroboration-only behaviour."""
from __future__ import annotations

import pandas as pd
import pytest

from scoring.combine import COMPANIES_HOUSE_TIER_WEIGHTS, SIGNAL_WEIGHTS, score_customers
from scoring.signals import companies_house as ch


def _table():
    # {normalized name: (reason, tier)}, mirroring load_controllers' shape.
    return {
        ch._normalize("Anne Boden"): ("Anne Boden — controls Boden Ventures Ltd (Companies House)", "match"),
        ch._normalize("Tom Blomfield"): ("Tom Blomfield — controls Blomfield Capital Ltd, a "
                                          "real estate company (Companies House)", "prime"),
    }


@pytest.fixture
def seeded_table(monkeypatch):
    """Make the whole engine score against ``_table()`` (the inert seed has only a placeholder)."""
    monkeypatch.setattr(ch, "load_controllers", lambda *a, **k: _table())
    return _table()


def test_exact_name_matches():
    hit, reason, tier = ch.match_name("Anne Boden", _table())
    assert hit and "Anne Boden" in reason and tier == "match"


def test_case_and_punctuation_insensitive():
    table = _table()
    assert ch.match_name("anne  boden", table)[0]
    assert ch.match_name("ANNE-BODEN", table)[0]


def test_partial_or_extra_tokens_do_not_match():
    table = _table()
    # exact-normalized match: a middle name or surname-only must NOT match
    assert not ch.match_name("Anne M Boden", table)[0]
    assert not ch.match_name("Boden", table)[0]
    assert not ch.match_name("Anne Bodenham", table)[0]


def test_flag_adds_columns():
    df = pd.DataFrame({"Name": ["Anne Boden", "Someone Else"]})
    out = ch.flag_companies_house(df, table=_table())
    assert list(out[ch.FLAG_COL]) == [True, False]
    assert out.loc[0, ch.REASON_COL] and out.loc[1, ch.REASON_COL] is None
    assert out.loc[0, ch.TYPE_COL] == "match" and out.loc[1, ch.TYPE_COL] is None


def test_missing_name_column_is_safe():
    out = ch.flag_companies_house(pd.DataFrame({"Email": ["a@b.com"]}), table=_table())
    assert list(out[ch.FLAG_COL]) == [False]


def test_reason_names_industry():
    # The reason should say what the SIC code indicates when an industry is present.
    assert ch._reason("Jane Marandi", "Marandi Investments Ltd", "real estate") == (
        "Jane Marandi — controls Marandi Investments Ltd, a real estate company (Companies House)")
    assert ch._reason("A B", "AB Ltd", "") == "A B — controls AB Ltd (Companies House)"
    # vowel-initial industries take "an"
    assert ", an architecture company" in ch._reason("F M", "FM Architecture Ltd", "architecture")
    assert ", an investment company" in ch._reason("D C", "DC IFA Ltd", "investment")


def test_seed_table_loads_inert_placeholder():
    # The committed seed ships INERT: the fictional placeholder loads, no real individual.
    table = ch.load_controllers(ch.UK_COMPANY_CONTROLLERS_FILE)
    assert ch._normalize("Ada Placeholder") in table
    reason, tier = table[ch._normalize("Ada Placeholder")]
    assert "Placeholder Holdings Ltd" in reason and tier == "match"


def test_corroboration_only_never_a_sole_basis(seeded_table):
    # Name matches CH only (nothing else fires) -> gated off, not a hidden VIC.
    df = pd.DataFrame([{"Name": "Anne Boden", "Email": "a@gmail.com", "Spent": 10}])
    scored = score_customers(df)
    assert scored.loc[0, "signal_count"] == 0
    assert not scored.loc[0, "hidden_vic"]
    assert not scored.loc[0, ch.FLAG_COL]  # flag suppressed for display consistency


def test_counts_when_a_core_signal_also_fires(seeded_table):
    # CH + a prime postcode -> CH now corroborates and is counted.
    df = pd.DataFrame([{"Name": "Anne Boden", "Email": "a@gmail.com",
                        "Spent": 10, "LATEST_BILLING_ZIP": "SW10 9SJ"}])
    scored = score_customers(df)
    assert scored.loc[0, ch.FLAG_COL]
    assert "Companies House" in scored.loc[0, "reasons"]
    assert scored.loc[0, "hidden_vic"]


def test_tier_lifts_the_score(seeded_table):
    # A 'prime' owner must corroborate more than a 'match' owner, given the same core signal.
    base = {"Email": "a@gmail.com", "Spent": 10, "LATEST_BILLING_ZIP": "SW10 9SJ"}
    match_row = score_customers(pd.DataFrame([{**base, "Name": "Anne Boden"}]))
    prime_row = score_customers(pd.DataFrame([{**base, "Name": "Tom Blomfield"}]))
    assert COMPANIES_HOUSE_TIER_WEIGHTS["prime"] > COMPANIES_HOUSE_TIER_WEIGHTS["match"]
    assert prime_row.loc[0, "signal_score"] > match_row.loc[0, "signal_score"]


def test_calibrated_base_scales_tier_weights(seeded_table):
    # Per-merchant calibration moves the base weight; tiered rows must scale with it
    # proportionally (tuned base / shipped default), not silently ignore it.
    base = {"Email": "a@gmail.com", "Spent": 10, "LATEST_BILLING_ZIP": "SW10 9SJ"}
    df = pd.DataFrame([{**base, "Name": "Tom Blomfield"}])   # 'prime' tier (weight 6)
    default = score_customers(df).loc[0, "signal_score"]
    doubled_weights = dict(SIGNAL_WEIGHTS)
    doubled_weights["companies_house"] = SIGNAL_WEIGHTS["companies_house"] * 2
    doubled = score_customers(df, weights=doubled_weights).loc[0, "signal_score"]
    # Doubling the base doubles the prime tier's contribution (6 -> 12): +6 on the score.
    assert doubled - default == COMPANIES_HOUSE_TIER_WEIGHTS["prime"]
