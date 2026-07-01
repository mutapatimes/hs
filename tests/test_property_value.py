"""Tests for the area property-value signal.

Property value is a WEALTH FACT, so this signal scores through the DEFAULT
score_customers path (it is not an origin proxy). It grades a customer by the median
property value of their postcode area, tiered ultra / prime / high.
"""
import pandas as pd

from scoring.combine import (
    COUNT_COL,
    HIDDEN_COL,
    ORIGIN_PROXY_SIGNALS,
    PROPERTY_TIER_WEIGHTS,
    REASONS_COL,
    SCORE_COL,
    score_customers,
)
from scoring.signals.property_value import (
    FLAG_COL,
    TIER_COL,
    _outcode,
    flag_property_value,
    load_values,
    match_postcode,
)

TABLE = load_values()


# ── the matcher ──────────────────────────────────────────────────────────────
def test_outcode_extraction():
    assert _outcode("SW10 9SJ") == "SW10"
    assert _outcode("SW109LG") == "SW10"     # no space
    assert _outcode("w1k 1aa") == "W1K"       # lower case
    assert _outcode("") is None
    assert _outcode(None) is None


def test_match_returns_tier_and_reason():
    hit, tier, reason = match_postcode("W1K 1AA", TABLE)
    assert hit and tier == "ultra"
    assert "Mayfair" in reason and "W1K" in reason

    hit, tier, _ = match_postcode("SW10 9SJ", TABLE)
    assert hit and tier == "prime"


def test_unlisted_and_placeholder_postcodes_do_not_match():
    assert match_postcode("E14 9GU", TABLE)[0] is False    # Canary Wharf: not listed
    assert match_postcode("LS1 1AA", TABLE)[0] is False     # Leeds city centre
    assert match_postcode("SW1A 1AA", TABLE)[0] is False    # Buckingham Palace placeholder


def test_best_address_wins_across_billing_and_shipping():
    df = pd.DataFrame([{"LATEST_BILLING_ZIP": "E14 9GU", "LATEST_SHIPPING_ZIP": "W1K 1AA"}])
    out = flag_property_value(df, table=TABLE)
    assert bool(out.loc[0, FLAG_COL]) and out.loc[0, TIER_COL] == "ultra"


def test_missing_columns_are_dormant():
    out = flag_property_value(pd.DataFrame({"x": [1]}), table=TABLE)
    assert not out[FLAG_COL].any()


# ── through the scoring pipeline (default path) ──────────────────────────────
def _row(zip_code):
    return pd.DataFrame([{"Name": "x", "Spent": 200, "EMAIL_ADDR": "x@gmail.com",
                          "LATEST_BILLING_ZIP": zip_code, "LATEST_SHIPPING_ZIP": zip_code,
                          "LATEST_BILLING_ADDRESS4": "United Kingdom"}])


def test_property_value_scores_by_default_and_is_not_an_origin_proxy():
    assert "property_value" not in ORIGIN_PROXY_SIGNALS
    # A customer whose ONLY tell is living in a high-value area, on the DEFAULT path.
    out = score_customers(_row("RG9 2AA")).iloc[0]   # Henley-on-Thames, 'high'
    assert out[COUNT_COL] == 1
    assert out[SCORE_COL] == PROPERTY_TIER_WEIGHTS["high"]
    assert bool(out[HIDDEN_COL])                      # £200 spend + a signal -> hidden VIC
    assert "Property value" in out[REASONS_COL]


def test_tier_grades_the_weight():
    # Barnes (prime) outscores Henley (high) on the same machinery. Use postcodes whose
    # outcode is NOT also on the hnwi list, so property_value is the sole geo tell.
    prime = score_customers(_row("SW13 9AA")).iloc[0]   # Barnes, 'prime', w3
    high = score_customers(_row("RG9 2AA")).iloc[0]     # Henley, 'high', w2
    assert prime[SCORE_COL] == PROPERTY_TIER_WEIGHTS["prime"]
    assert high[SCORE_COL] == PROPERTY_TIER_WEIGHTS["high"]
    assert prime[SCORE_COL] > high[SCORE_COL]
