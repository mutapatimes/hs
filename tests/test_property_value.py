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
    PROPERTY_MAX_WEIGHT,
    PROPERTY_MIN_WEIGHT,
    REASONS_COL,
    SCORE_COL,
    property_value_weight,
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


# ── exact full-postcode matching ─────────────────────────────────────────────
def test_exact_full_postcode_matches_the_actual_house():
    # The exact postcode is 'ultra'; its district is only 'high'. Exact must win.
    table = {
        "W1K1BB": {"tier": "ultra", "price": 5_000_000, "area": "Mayfair"},   # the house
        "W1K":    {"tier": "high",  "price": 650_000,   "area": "Mayfair"},   # the district
    }
    hit, tier, reason = match_postcode("W1K 1BB", table)
    assert hit and tier == "ultra" and "W1K 1BB" in reason      # actual address wins

    # A different postcode in the same district falls back to the district tier.
    hit2, tier2, reason2 = match_postcode("W1K 9ZZ", table)
    assert hit2 and tier2 == "high" and "(W1K)" in reason2


def test_exact_match_scans_billing_and_shipping():
    table = {"SW1X7XL": {"tier": "ultra", "price": 6_000_000, "area": "Belgravia"}}
    df = pd.DataFrame([{"LATEST_BILLING_ZIP": "E1 6AN", "LATEST_SHIPPING_ZIP": "SW1X 7XL"}])
    out = flag_property_value(df, table=table)
    assert bool(out.loc[0, FLAG_COL]) and out.loc[0, TIER_COL] == "ultra"


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


def test_property_weight_scales_with_the_actual_value():
    # A £50M home must outweigh a £2M, which must outweigh a £700k.
    w700 = float(property_value_weight(700_000))
    w2m = float(property_value_weight(2_000_000))
    w50m = float(property_value_weight(50_000_000))
    assert w700 < w2m < w50m
    assert abs(float(property_value_weight(600_000)) - PROPERTY_MIN_WEIGHT) < 1e-9   # floor anchor
    assert float(property_value_weight(500_000_000)) == PROPERTY_MAX_WEIGHT          # bounded


def test_property_value_scores_by_default_and_is_not_an_origin_proxy():
    assert "property_value" not in ORIGIN_PROXY_SIGNALS
    # A customer whose ONLY tell is living in a high-value area, on the DEFAULT path.
    out = score_customers(_row("RG9 2AA")).iloc[0]   # Henley-on-Thames, 'high'
    assert out[COUNT_COL] == 1
    assert out[SCORE_COL] >= PROPERTY_MIN_WEIGHT      # at least the floor weight
    assert bool(out[HIDDEN_COL])                      # £200 spend + a signal -> hidden VIC
    assert "Prime area" in out[REASONS_COL]


def test_higher_value_area_outscores_lower():
    # Barnes (pricier, prime) outscores Henley (high) on the same machinery, now graded by
    # the actual median price. Outcodes NOT on the hnwi list, so property_value is the sole tell.
    prime = score_customers(_row("SW13 9AA")).iloc[0]   # Barnes, prime
    high = score_customers(_row("RG9 2AA")).iloc[0]     # Henley, high
    assert prime[SCORE_COL] > high[SCORE_COL] >= PROPERTY_MIN_WEIGHT
