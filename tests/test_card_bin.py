"""Tests for the premium-card (BIN) signal."""
import pandas as pd

from scoring.signals.card_bin import (
    FLAG_COL,
    REASON_COL,
    flag_card_bin,
    load_bins,
    match_bin,
)

# Deterministic test BIN list (independent of the shipped template values).
BINS = [
    ("4751509", "Coutts", "private_bank"),   # 7-digit, should beat the 6-digit below
    ("475110", "Other Bank", "premium"),
    ("552350", "World Elite", "ultra_premium"),
]


def test_match_longest_prefix_wins():
    matched, reason = match_bin("47515091234", BINS)
    assert matched and reason == "Coutts (private_bank)"


def test_match_with_brand_appended():
    matched, reason = match_bin("55235012", BINS, company="Mastercard")
    assert matched and reason == "World Elite (ultra_premium) [Mastercard]"


def test_no_match_and_blank():
    assert match_bin("400000", BINS) == (False, None)
    assert match_bin(None, BINS) == (False, None)
    assert match_bin("", BINS) == (False, None)


def test_dormant_when_no_bin_column():
    """In the current (non-Shopify) data there is no BIN column -> flags nothing."""
    df = pd.DataFrame({"Name": ["a", "b"], "Spent": [1, 2]})
    out = flag_card_bin(df, BINS)
    assert out[FLAG_COL].tolist() == [False, False]
    assert out[REASON_COL].tolist() == [None, None]


def test_fires_when_bin_column_present():
    df = pd.DataFrame(
        {
            "credit_card_bin": ["47515099", "400000", None],   # starts with 4751509
            "credit_card_company": ["Visa", "Visa", None],
        }
    )
    out = flag_card_bin(df, BINS)
    assert out[FLAG_COL].tolist() == [True, False, False]
    assert out.loc[0, REASON_COL] == "Coutts (private_bank) [Visa]"


def test_shipped_template_loads():
    bins = load_bins()
    assert len(bins) >= 1            # the example rows parse
    assert all(p.isdigit() for p, _, _ in bins)
