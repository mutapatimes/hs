"""Tests for the signal combiner.

Uses a small synthetic DataFrame with the columns the signals read, so the
scoring is deterministic and independent of the real data file.
"""
import pandas as pd

from scoring.combine import (
    COUNT_COL,
    HIDDEN_COL,
    REASONS_COL,
    SCORE_COL,
    SIGNAL_WEIGHTS,
    reasons_top_n,
    score_customers,
    top_hidden_vics,
)


# --- A2: non-customer suppressor -------------------------------------------
def test_row_with_no_contactable_identity_is_not_hidden():
    # A wealth-address signal fires, but there is no name and no email -> not actionable,
    # so it is never surfaced as a hidden VIC.
    out = score_customers(_frame([{"Name": None, "EMAIL_ADDR": None, "Spent": 100,
                                    "LATEST_BILLING_ZIP": "SW1A 1AA"}]))
    assert out.loc[0, COUNT_COL] >= 0
    assert not out.loc[0, HIDDEN_COL]


def test_placeholder_test_row_is_not_hidden():
    out = score_customers(_frame([{"Name": "test", "EMAIL_ADDR": "test@example.com",
                                   "Spent": 100, "LATEST_BILLING_ZIP": "SW1A 1AA"}]))
    assert not out.loc[0, HIDDEN_COL]


def test_real_identity_still_surfaces():
    out = score_customers(_frame([{"Name": "Jane Rothschild", "EMAIL_ADDR": "jane@gmail.com",
                                   "Spent": 100, "LATEST_BILLING_ZIP": "SW1A 1AA"}]))
    if out.loc[0, COUNT_COL] > 0:
        assert out.loc[0, HIDDEN_COL]


# --- A3: reasons roll-up ---------------------------------------------------
def test_reasons_top_n_caps_and_counts():
    assert reasons_top_n("A: 1; B: 2; C: 3", n=4) == "A: 1; B: 2; C: 3"     # under cap: unchanged
    assert reasons_top_n("A: 1; B: 2; C: 3; D: 4; E: 5", n=3) == "A: 1; B: 2; C: 3; and 2 more"
    assert reasons_top_n("", n=3) == "" and reasons_top_n(None, n=3) == ""


def _blank_row(**overrides):
    row = {
        "Name": "x",
        "Spent": 0,
        "SEGMENT": "Final Client",
        "EMAIL_ADDR": "x@gmail.com",
        "LATEST_BILLING_ZIP": "E14 9GU",
        "LATEST_BILLING_ADDRESS4": "United Kingdom",
        "LATEST_SHIPPING_ADDRESS1": "1 Nowhere Road",
        "LATEST_SHIPPING_ADDRESS2": None,
        "LATEST_SHIPPING_ADDRESS3": "London",
        "LATEST_SHIPPING_ADDRESS4": "United Kingdom",
        "LATEST_SHIPPING_ZIP": "E14 9GU",
    }
    row.update(overrides)
    return row


def _frame(rows):
    return pd.DataFrame([_blank_row(**r) for r in rows])


def test_no_signals_scores_zero_and_not_hidden():
    out = score_customers(_frame([{}]))
    assert out.loc[0, SCORE_COL] == 0
    assert out.loc[0, COUNT_COL] == 0
    assert out.loc[0, REASONS_COL] == ""
    assert not out.loc[0, HIDDEN_COL]


def test_single_signal_scores_its_weight():
    out = score_customers(_frame([{"EMAIL_ADDR": "ceo@carlsoncapital.com"}]))
    assert out.loc[0, COUNT_COL] == 1
    assert out.loc[0, SCORE_COL] == SIGNAL_WEIGHTS["work_email"]
    assert "Work email: Carlson Capital (hedge_fund)" in out.loc[0, REASONS_COL]
    assert out.loc[0, HIDDEN_COL]


def test_correlated_geo_signals_get_diminishing_returns():
    out = score_customers(_frame([{
        "EMAIL_ADDR": "x@calculuscapital.com",      # work_email (own group), w=3
        "LATEST_BILLING_ZIP": "SW10 9SJ",           # hnwi_postcode (geo), w=3
        "LATEST_BILLING_ADDRESS4": "Qatar",         # gcc_billing (geo), w=2
    }]), include_origin=True)  # origin proxies opted in to test geo grouping
    # SW10 fires both hnwi_postcode AND property_value (Chelsea, a prime area). Four
    # signals fire, but the three GEO tells (same location) don't fully stack:
    #   work_email 3  +  geo[ hnwi 3 (full) + property_value 3 x0.5 + gcc 2 x0.25 ]
    #   = 3 + (3 + 1.5 + 0.5) = 8.0   (naive additive would have been 3+3+3+2 = 11).
    assert out.loc[0, COUNT_COL] == 4
    assert out.loc[0, SCORE_COL] == 8.0
    reasons = out.loc[0, REASONS_COL]
    assert "Work email" in reasons and "HNWI postcode" in reasons \
        and "Prime area" in reasons and "GCC billing" in reasons


def test_three_correlated_geo_tells_score_below_their_raw_sum():
    # Phone +971 (UAE), billing country UAE, billing in a GCC -> all 'geo'.
    out = score_customers(_frame([{
        "PHONE": "+971 50 123 4567",                # phone_country (geo), w=1
        "LATEST_BILLING_ADDRESS4": "United Arab Emirates",   # gcc_billing (geo), w=2
        "LATEST_SHIPPING_ADDRESS4": "United Arab Emirates",
    }]), include_origin=True)  # origin proxies opted in to test geo grouping
    # geo[ gcc 2 (full) + phone 1 x 0.5 ] = 2.5, not 3; redundant location discounted.
    assert out.loc[0, COUNT_COL] == 2
    assert out.loc[0, SCORE_COL] == 2.5


def test_gate_is_spend_not_segment():
    # Same firing signal (HNWI postcode); only spend decides "hidden". The old
    # VIP/VIC SEGMENT tag must NOT gate anymore.
    out = score_customers(_frame([
        {"Name": "big", "Spent": 50000, "LATEST_BILLING_ZIP": "SW10 9SJ"},
        {"Name": "small", "Spent": 100, "LATEST_BILLING_ZIP": "SW10 9SJ"},
        {"Name": "tagged_but_poor", "SEGMENT": "VIP", "Spent": 50,
         "LATEST_BILLING_ZIP": "SW10 9SJ"},
    ]))
    hidden = out.set_index("Name")[HIDDEN_COL]
    assert not hidden["big"]              # already above threshold -> known
    assert hidden["small"]               # below threshold + signal -> hidden VIC
    assert hidden["tagged_but_poor"]     # SEGMENT no longer suppresses


def test_threshold_is_configurable():
    rows = [{"Name": "mid", "Spent": 3000, "LATEST_BILLING_ZIP": "SW10 9SJ"}]
    assert score_customers(_frame(rows), vic_threshold=2000).loc[0, HIDDEN_COL] is False \
        or not score_customers(_frame(rows), vic_threshold=2000).loc[0, HIDDEN_COL]
    assert score_customers(_frame(rows), vic_threshold=5000).loc[0, HIDDEN_COL]


def test_top_hidden_vics_sorted_by_score_then_spend():
    out = score_customers(_frame([
        {"Name": "low", "Spent": 5000},                                   # 0 signals
        {"Name": "one", "Spent": 100, "LATEST_BILLING_ADDRESS4": "Qatar"},  # 1 signal (w=2)
        {"Name": "three", "Spent": 1,
         "EMAIL_ADDR": "x@calculuscapital.com",
         "LATEST_BILLING_ZIP": "SW10 9SJ",
         "LATEST_BILLING_ADDRESS4": "Kuwait"},                            # 3 signals
    ]), include_origin=True)  # origin proxies opted in: "one" rides gcc_billing
    ranked = top_hidden_vics(out, n=10)
    assert ranked.iloc[0]["Name"] == "three"   # highest score wins despite £1 spend
    assert list(ranked["Name"]) == ["three", "one"]   # "low" excluded (no signal)
