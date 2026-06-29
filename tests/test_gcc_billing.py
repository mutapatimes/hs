"""Tests for the GCC billing-country signal.

Country names are not PII, so these are used verbatim. The values are real
billing countries seen in sample_data/sample.xlsx, plus spelling variants and
the key near-misses (Romania -> "OMAN" substring; non-GCC Middle East).
"""
import pandas as pd

from scoring.signals.gcc_billing import (
    COUNTRY_COL,
    FLAG_COL,
    flag_gcc_billing,
    load_gcc_countries,
    match_country,
)

# (billing country value, expected canonical country or None)
CASES = [
    # --- should match (real spellings + variants) ---
    ("United Arab Emirates", "United Arab Emirates"),
    ("Kuwait", "Kuwait"),
    ("Qatar", "Qatar"),
    ("Saudi Arabia", "Saudi Arabia"),
    ("Bahrain", "Bahrain"),
    ("UAE", "United Arab Emirates"),                  # abbreviation
    ("KSA", "Saudi Arabia"),                          # abbreviation
    ("  saudi arabia ", "Saudi Arabia"),              # lower-case + padding
    ("Sultanate of Oman", "Oman"),                    # long form
    # --- should NOT match ---
    ("Romania", None),                                # contains substring "OMAN"
    ("United States", None),
    ("United Kingdom", None),
    ("Israel", None),                                 # Middle East, not GCC
    ("Turkey", None),
    ("Egypt", None),                                  # Middle East, not GCC
    ("53 Au Pui Wan Street", None),                   # junk in the country field
]


def test_country_cases():
    countries = load_gcc_countries()
    for value, expected in CASES:
        matched, canonical = match_country(value, countries)
        assert matched is (expected is not None), f"{value!r} -> {matched}"
        assert canonical == expected, f"{value!r} -> {canonical} (wanted {expected})"


def test_dataframe_helper():
    countries = load_gcc_countries()
    df = pd.DataFrame(
        {"LATEST_BILLING_ADDRESS4": ["Qatar", "Romania", None, "uae"]}
    )
    out = flag_gcc_billing(df, countries)
    assert out[FLAG_COL].tolist() == [True, False, False, True]
    assert out[COUNTRY_COL].tolist() == ["Qatar", None, None, "United Arab Emirates"]


def test_blank_not_flagged():
    countries = load_gcc_countries()
    assert match_country(None, countries) == (False, None)
    assert match_country("", countries) == (False, None)
