"""Tests for the tax-haven country signal (billing and/or shipping)."""
import pandas as pd

from scoring.signals.tax_haven import (
    FLAG_COL,
    REASON_COL,
    flag_tax_haven,
    load_tax_havens,
    match_row,
)


def test_match_billing_or_shipping_with_field_in_reason():
    havens = load_tax_havens()
    assert match_row("Jersey", "United Kingdom", havens) == (True, "Jersey (billing)")
    assert match_row("United Kingdom", "Monaco", havens) == (True, "Monaco (shipping)")
    assert match_row("United Kingdom", "United States", havens) == (False, None)


def test_billing_takes_priority_when_both_match():
    havens = load_tax_havens()
    matched, reason = match_row("Guernsey", "Switzerland", havens)
    assert matched and reason == "Guernsey (billing)"


def test_near_miss_does_not_match():
    havens = load_tax_havens()
    # "Romania" contains "OMAN" but Oman isn't a tax haven here anyway; the point
    # is whole-word matching still holds for the country list.
    assert match_row("Romania", "United Kingdom", havens) == (False, None)


def test_dataframe_helper():
    havens = load_tax_havens()
    df = pd.DataFrame(
        {
            "LATEST_BILLING_ADDRESS4": ["Switzerland", "United Kingdom", "France"],
            "LATEST_SHIPPING_ADDRESS4": ["Switzerland", "Isle Of Man", "France"],
        }
    )
    out = flag_tax_haven(df, havens)
    assert out[FLAG_COL].tolist() == [True, True, False]
    assert out[REASON_COL].tolist() == [
        "Switzerland (billing)", "Isle of Man (shipping)", None
    ]
