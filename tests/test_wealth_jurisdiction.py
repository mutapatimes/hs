"""High-value residential jurisdiction signal (Bucket 1 — was tax_haven).

On by default, factual reason text, recurated from property-market data.
"""
import pandas as pd

from scoring.combine import REASONS_COL, score_customers
from scoring.signals.wealth_jurisdiction import (
    FLAG_COL,
    REASON_COL,
    flag_wealth_jurisdiction,
    load_wealth_jurisdictions,
    match_row,
)


def test_match_billing_or_shipping_with_factual_reason():
    js = load_wealth_jurisdictions()
    assert match_row("Jersey", "United Kingdom", js) == (
        True, "Jersey — high-value residential jurisdiction (billing)")
    assert match_row("United Kingdom", "Monaco", js) == (
        True, "Monaco — high-value residential jurisdiction (shipping)")
    assert match_row("United Kingdom", "United States", js) == (False, None)


def test_reason_never_says_tax_haven_or_offshore():
    js = load_wealth_jurisdictions()
    _, reason = match_row("Monaco", "United Kingdom", js)
    assert "tax haven" not in reason.lower() and "offshore" not in reason.lower()


def test_billing_takes_priority_when_both_match():
    js = load_wealth_jurisdictions()
    matched, reason = match_row("Guernsey", "Jersey", js)
    assert matched and reason.startswith("Guernsey")


def test_populous_countries_dropped_from_bucket_1():
    # Switzerland / Luxembourg / Malta / Cyprus are no longer whole-country wealth tells
    # (their prime districts live in intl_postcode / hnw_area instead).
    js = load_wealth_jurisdictions()
    for dropped in ("Switzerland", "Luxembourg", "Malta", "Cyprus"):
        assert match_row(dropped, "United Kingdom", js) == (False, None)


def test_dataframe_helper():
    js = load_wealth_jurisdictions()
    df = pd.DataFrame({
        "LATEST_BILLING_ADDRESS4": ["Monaco", "United Kingdom", "France"],
        "LATEST_SHIPPING_ADDRESS4": ["Monaco", "Isle Of Man", "France"],
    })
    out = flag_wealth_jurisdiction(df, js)
    assert out[FLAG_COL].tolist() == [True, True, False]
    assert out[REASON_COL].tolist()[0].startswith("Monaco — high-value residential jurisdiction")
    assert out[REASON_COL].tolist()[1].startswith("Isle of Man — high-value residential jurisdiction")
    assert out[REASON_COL].tolist()[2] is None


def test_fires_by_default_now_not_gated():
    # It used to be gated as "tax_haven"; as a wealth fact it now scores by default.
    df = pd.DataFrame([{"Name": "A", "Email": "a@gmail.com", "Spent": 50,
                        "LATEST_BILLING_ADDRESS4": "Monaco"}])
    reasons = score_customers(df).loc[0, REASONS_COL]
    assert "High-value area" in reasons and "Monaco" in reasons
