"""Tests for the HNWI postcode signal.

Uses 10 REAL billing postcodes taken from the customer data (the postcode
field only — no names/emails — so no identifying PII is committed to git).
"""
import pandas as pd

from scoring.signals.hnwi_postcode import (
    FLAG_COL,
    REASON_COL,
    flag_hnwi_postcode,
    load_prefixes,
    match_postcode,
)

# 10 real LATEST_BILLING_ZIP values from sample_data/sample.xlsx.
# The shipped list now contains the whole SW10 district (plus specific units),
# so every SW10 postcode matches; SW1/SW3/SW1X/etc. still must not.
# (postcode, should_match, expected_reason)
REAL_ROWS = [
    ("SW10 9SJ", True, "SW10 9SJ"),  # exact unit wins (listed before the district)
    ("SW10 9JP", True, "SW10"),      # matched by the SW10 district
    ("SW10 0AW", True, "SW10"),
    ("SW109LG", True, "SW10"),       # SW10 even with the space missing
    ("SW1 8LL", False, None),        # SW1 district -> must NOT match SW10/SW1X/SW1W
    ("SW3 1BW", True, "SW3"),        # Chelsea district now in the list
    ("SW1X 7DE", True, "SW1X"),      # Belgravia district now in the list
    ("E14 9GU", False, None),        # Canary Wharf
    ("EC1V 2AF", False, None),       # City
    ("00000", False, None),          # junk/foreign zip
]


def test_ten_real_rows_against_shipped_list():
    prefixes = load_prefixes()
    df = pd.DataFrame({"LATEST_BILLING_ZIP": [pc for pc, _, _ in REAL_ROWS]})

    result = flag_hnwi_postcode(df, prefixes)

    assert result[FLAG_COL].tolist() == [should for _, should, _ in REAL_ROWS]
    assert result[REASON_COL].tolist() == [reason for _, _, reason in REAL_ROWS]

    # 6 prime-London customers flagged; the exact SW10 unit keeps its precise reason.
    assert result[FLAG_COL].sum() == 6


def test_district_prefix_broadens_matches():
    """Show the granularity feature: a district prefix catches the whole area."""
    prefixes = ["SW10"]  # district-level, as the user could add
    hits = [match_postcode(pc, prefixes)[0] for pc, _, _ in REAL_ROWS]
    # All four real SW10* postcodes now match; SW1/SW3/SW1X/etc still don't.
    assert hits == [True, True, True, True, False, False, False, False, False, False]


def test_sector_prefix_matches_sector_only():
    """A sector prefix matches the sector but respects unit boundaries."""
    matched, reason = match_postcode("SW10 9JP", ["SW10 9"])
    assert matched and reason == "SW10 9"
    # Different sector in the same district is not matched.
    assert match_postcode("SW10 0AW", ["SW10 9"])[0] is False


def test_blank_postcode_is_not_flagged():
    assert match_postcode(None, ["SW10 9SJ"]) == (False, None)
    assert match_postcode("", ["SW10 9SJ"]) == (False, None)
