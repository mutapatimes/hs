"""Tests for the hotel-concierge signal + the free-provider fix (naver/yahoo)."""
import pandas as pd

from scoring.combine import REASONS_COL, score_customers
from scoring.signals.custom_email import flag_custom_email
from scoring.signals.hotel_concierge import flag_hotel_concierge


def test_hotel_domain_flags_as_hotel_concierge_not_work_email():
    out = score_customers(pd.DataFrame([{
        "Name": "Concierge", "Spent": 1410,
        "EMAIL_ADDR": "concierge.london@corinthia.com",
    }]))
    reasons = out.loc[0, REASONS_COL]
    assert "Hotel concierge: Corinthia" in reasons
    assert "Work email" not in reasons          # no longer mislabelled
    assert "Custom domain" not in reasons        # nor a generic custom domain


def test_hotel_flag_and_missing_column():
    df = pd.DataFrame({"EMAIL_ADDR": ["a@mandarinoriental.com", "b@gmail.com"]})
    out = flag_hotel_concierge(df)
    assert out["hotel_concierge"].tolist() == [True, False]
    assert "Mandarin Oriental" in str(out.loc[0, "hotel_concierge_reason"])
    assert not flag_hotel_concierge(pd.DataFrame({"x": [1]}))["hotel_concierge"].any()


def test_chain_domain_fires_on_role_email_only_not_personal_name():
    df = pd.DataFrame({"EMAIL_ADDR": [
        "concierge@marriott.com",        # role -> fires (luxury property desk)
        "guestrelations.venice@hyatt.com",  # role -> fires
        "john.smith@marriott.com",       # personal name -> must NOT fire
        "olivia@hilton.com",             # personal name -> must NOT fire
    ]})
    out = flag_hotel_concierge(df)
    assert out["hotel_concierge"].tolist() == [True, True, False, False]
    assert "Marriott (concierge desk)" in str(out.loc[0, "hotel_concierge_reason"])


def test_chain_personal_email_is_not_a_custom_domain_either():
    out = flag_custom_email(pd.DataFrame({"EMAIL_ADDR": ["john.smith@marriott.com"]}))
    assert not out["custom_email"].any()


def test_naver_and_yahoo_variants_are_not_custom_domains():
    # The reported bug: naver.com (Korean webmail) + yahoo country variants were
    # wrongly flagged as custom domains.
    df = pd.DataFrame({"EMAIL_ADDR": [
        "joanne@naver.com", "x@yahoo.co.jp", "y@daum.net", "z@bespoke-firm.io",
    ]})
    out = flag_custom_email(df)
    assert out["custom_email"].tolist() == [False, False, False, True]
