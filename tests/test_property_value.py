"""Tests for the property-value signals.

Two signals share one reference table and both are WEALTH FACTS (not origin proxies):
  - property_value : EXACT full postcode (the actual house), weight scales with median price.
  - property_area  : the OUTCODE / district (a high-net-worth area), graded by tier.
Neither surfaces the raw price, only a value GRADE.
"""
import pandas as pd

from scoring.combine import (
    COUNT_COL,
    HIDDEN_COL,
    ORIGIN_PROXY_SIGNALS,
    PROPERTY_AREA_WEIGHTS,
    PROPERTY_MAX_WEIGHT,
    PROPERTY_MIN_WEIGHT,
    REASONS_COL,
    SCORE_COL,
    property_value_weight,
    score_customers,
)
from scoring.signals.property_value import (
    AREA_FLAG_COL,
    AREA_TIER_COL,
    FLAG_COL,
    TIER_COL,
    _outcode,
    flag_property_area,
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


def test_match_returns_grade_not_price():
    # Seed is district-level, so this matches the area. Reason is a GRADE, never a £ figure.
    hit, tier, reason = match_postcode("W1K 1AA", TABLE)
    assert hit and tier == "ultra"
    assert "Ultra-prime" in reason and "Mayfair" in reason
    assert "£" not in reason and not any(ch.isdigit() for ch in reason)  # no price shown


def test_unlisted_and_placeholder_postcodes_do_not_match():
    assert match_postcode("E14 9GU", TABLE)[0] is False    # Canary Wharf: not listed
    assert match_postcode("LS1 1AA", TABLE)[0] is False     # Leeds city centre
    assert match_postcode("SW1A 1AA", TABLE)[0] is False    # Buckingham Palace placeholder


# ── exact full-postcode (the house) vs the area ──────────────────────────────
def test_exact_full_postcode_matches_the_actual_house():
    # The exact postcode is 'ultra'; its district is only 'high'. Exact must win, and the
    # reason names the exact postcode with a grade (no price).
    table = {
        "W1K1BB": {"tier": "ultra", "price": 5_000_000, "area": "Mayfair"},   # the house
        "W1K":    {"tier": "high",  "price": 650_000,   "area": "Mayfair"},   # the district
    }
    hit, tier, reason = match_postcode("W1K 1BB", table)
    assert hit and tier == "ultra" and "W1K 1BB" in reason and "Ultra-prime" in reason

    out = flag_property_value(pd.DataFrame([{"LATEST_BILLING_ZIP": "W1K 1BB"}]), table=table)
    assert bool(out.loc[0, FLAG_COL]) and out.loc[0, TIER_COL] == "ultra"
    # A different postcode in the same district does NOT fire the exact-house signal.
    out2 = flag_property_value(pd.DataFrame([{"LATEST_BILLING_ZIP": "W1K 9ZZ"}]), table=table)
    assert not bool(out2.loc[0, FLAG_COL])


def test_area_matches_the_district():
    table = {"W1K": {"tier": "ultra", "price": 3_400_000, "area": "Mayfair"}}
    out = flag_property_area(pd.DataFrame([{"LATEST_BILLING_ZIP": "W1K 9ZZ"}]), table=table)
    assert bool(out.loc[0, AREA_FLAG_COL]) and out.loc[0, AREA_TIER_COL] == "ultra"


def test_exact_and_area_scan_billing_and_shipping():
    # The higher-value of the two addresses wins, for both signals.
    ex = {"SW1X7XL": {"tier": "ultra", "price": 6_000_000, "area": "Belgravia"}}
    df = pd.DataFrame([{"LATEST_BILLING_ZIP": "E1 6AN", "LATEST_SHIPPING_ZIP": "SW1X 7XL"}])
    assert bool(flag_property_value(df, table=ex).loc[0, FLAG_COL])

    area = pd.DataFrame([{"LATEST_BILLING_ZIP": "E14 9GU", "LATEST_SHIPPING_ZIP": "W1K 1AA"}])
    out = flag_property_area(area, table=TABLE)
    assert bool(out.loc[0, AREA_FLAG_COL]) and out.loc[0, AREA_TIER_COL] == "ultra"


def test_missing_columns_are_dormant():
    assert not flag_property_value(pd.DataFrame({"x": [1]}), table=TABLE)[FLAG_COL].any()
    assert not flag_property_area(pd.DataFrame({"x": [1]}), table=TABLE)[AREA_FLAG_COL].any()


# ── the exact-house weight scales with the actual value ──────────────────────
def test_property_weight_scales_with_the_actual_value():
    # A £50M home must outweigh a £2M, which must outweigh a £700k.
    w700 = float(property_value_weight(700_000))
    w2m = float(property_value_weight(2_000_000))
    w50m = float(property_value_weight(50_000_000))
    assert w700 < w2m < w50m
    assert abs(float(property_value_weight(600_000)) - PROPERTY_MIN_WEIGHT) < 1e-9   # floor anchor
    assert float(property_value_weight(500_000_000)) == PROPERTY_MAX_WEIGHT          # bounded


# ── through the scoring pipeline (default path, seed = district-level) ────────
def _row(zip_code):
    return pd.DataFrame([{"Name": "x", "Spent": 200, "EMAIL_ADDR": "x@gmail.com",
                          "LATEST_BILLING_ZIP": zip_code, "LATEST_SHIPPING_ZIP": zip_code,
                          "LATEST_BILLING_ADDRESS4": "United Kingdom"}])


def test_area_scores_by_default_and_is_not_an_origin_proxy():
    assert "property_area" not in ORIGIN_PROXY_SIGNALS
    out = score_customers(_row("RG9 2AA")).iloc[0]   # Henley-on-Thames, 'high' district
    assert out[COUNT_COL] == 1
    assert out[SCORE_COL] == PROPERTY_AREA_WEIGHTS["high"]
    assert bool(out[HIDDEN_COL])                      # £200 spend + a signal -> hidden VIC
    assert "Prime area" in out[REASONS_COL] and "High-value" in out[REASONS_COL]


def test_higher_value_area_outscores_lower():
    # Barnes (prime district) outscores Henley (high district). Outcodes NOT on the hnwi list,
    # so property_area is the sole tell.
    prime = score_customers(_row("SW13 9AA")).iloc[0]   # Barnes, prime
    high = score_customers(_row("RG9 2AA")).iloc[0]     # Henley, high
    assert prime[SCORE_COL] == PROPERTY_AREA_WEIGHTS["prime"]
    assert high[SCORE_COL] == PROPERTY_AREA_WEIGHTS["high"]
    assert prime[SCORE_COL] > high[SCORE_COL]
