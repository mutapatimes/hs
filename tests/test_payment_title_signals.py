"""Tests for the §3 payment/checkout and §4 post-nominal signals."""
import pandas as pd

from scoring.signals.card_brand import flag_card_brand
from scoring.signals.foreign_currency import flag_foreign_currency
from scoring.signals.post_nominal import flag_post_nominal, load_honours, match_name


# --- §4 post-nominal honours -------------------------------------------------
def test_post_nominal_matches_honours_as_standalone_tokens():
    h = load_honours()
    assert match_name("Sir Tim Berners-Lee KBE FRS", h)[0]
    assert "Order of the British Empire" in match_name("Jane Doe OBE", h)[1]
    assert match_name("John Smith", h) == (False, None)
    # Initials must NOT be read as the honour "KC".
    assert match_name("K. C. Jones", h) == (False, None)


def test_flag_post_nominal_frame_and_missing_column():
    out = flag_post_nominal(pd.DataFrame({"Name": ["Ada Lovelace CBE", "Bob Bobson"]}))
    assert out["post_nominal"].tolist() == [True, False]
    assert not flag_post_nominal(pd.DataFrame({"x": [1]}))["post_nominal"].any()


# --- §3 foreign currency -----------------------------------------------------
def test_foreign_currency_flags_non_home_currency():
    df = pd.DataFrame({"currency": ["USD", "GBP", "AED", None]})
    out = flag_foreign_currency(df, home="GBP")
    assert out["foreign_currency"].tolist() == [True, False, True, False]
    assert "USD" in str(out.loc[0, "foreign_currency_reason"])


def test_foreign_currency_dormant_without_column():
    assert not flag_foreign_currency(pd.DataFrame({"Spent": [1]}))["foreign_currency"].any()


# --- §3 premium card brand ---------------------------------------------------
def test_card_brand_flags_amex_and_diners_only():
    df = pd.DataFrame({"credit_card_company": ["American Express", "Visa", "Diners Club", None]})
    out = flag_card_brand(df)
    assert out["card_brand"].tolist() == [True, False, True, False]


def test_card_brand_dormant_without_column():
    assert not flag_card_brand(pd.DataFrame({"Spent": [1]}))["card_brand"].any()
