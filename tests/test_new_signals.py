"""Tests for the US-ZIP, premium-email, custom-domain, and alumni signals."""
import pandas as pd

from scoring.signals.custom_email import flag_custom_email, match_email as match_custom
from scoring.signals.elite_alumni import flag_elite_alumni
from scoring.signals.premium_email import (
    flag_premium_email,
    load_providers,
    match_email as match_premium,
)
from scoring.signals.us_zip import flag_us_zip, match_zip, load_zips


# --- US prime ZIP -----------------------------------------------------------
def test_us_zip_matches_and_handles_zip_plus_four():
    zips = load_zips()
    assert match_zip("90210", zips)[0]
    assert match_zip("90210-1234", zips)[0]          # ZIP+4 reduced to 5
    assert match_zip("10065", zips)[0]


def test_us_zip_ignores_uk_postcodes_and_non_prime():
    zips = load_zips()
    assert not match_zip("SW1W 8AB", zips)[0]         # UK never yields 5 digits
    assert not match_zip("00000", zips)[0]


def test_flag_us_zip_frame():
    df = pd.DataFrame({"LATEST_BILLING_ZIP": ["90210", "SW1X 7XL", None]})
    out = flag_us_zip(df)
    assert list(out["us_hnwi_zip"]) == [True, False, False]
    assert "Beverly Hills" in str(out.loc[0, "us_hnwi_zip_reason"])


# --- Premium / luxury ESP email --------------------------------------------
def test_premium_email_flags_mac_and_hey_and_superhuman():
    providers = {"mac.com": "Apple .Mac", "hey.com": "HEY", "superhuman.com": "Superhuman"}
    assert match_premium("rich@mac.com", providers)[0]
    assert match_premium("a@hey.com", providers)[1] == "HEY"
    assert match_premium("staff@superhuman.com", providers)[0]
    assert not match_premium("normal@gmail.com", providers)[0]


def test_flag_premium_email_frame_uses_reference_file():
    df = pd.DataFrame({"EMAIL_ADDR": ["x@mac.com", "y@gmail.com", "z@hey.com"]})
    out = flag_premium_email(df)
    assert list(out["premium_email"]) == [True, False, True]


def test_me_com_is_now_premium_not_free():
    providers = load_providers()
    assert "me.com" in providers            # reclassified as legacy paid Apple
    out = flag_premium_email(pd.DataFrame({"EMAIL_ADDR": ["a@me.com"]}))
    assert out["premium_email"].tolist() == [True]


# --- Elite-university alumni ------------------------------------------------
def test_elite_alumni_flags_ivy_and_business_school():
    df = pd.DataFrame({"EMAIL_ADDR": [
        "a@post.harvard.edu", "b@wharton.upenn.edu", "c@stanfordalumni.org",
        "d@gmail.com", "e@college.harvard.edu",  # bare student domain not listed
    ]})
    out = flag_elite_alumni(df)
    assert out["elite_alumni"].tolist() == [True, True, True, False, False]
    assert "Harvard" in str(out.loc[0, "elite_alumni_reason"])


# --- Custom / vanity domain (weak) -----------------------------------------
def test_custom_email_excludes_free_premium_and_employer():
    excluded = {"gmail.com", "mac.com", "gs.com"}
    assert match_custom("ceo@myfamilyoffice.xyz", excluded) == (True, "myfamilyoffice.xyz")
    assert not match_custom("a@gmail.com", excluded)[0]    # free
    assert not match_custom("a@mac.com", excluded)[0]      # premium
    assert not match_custom("a@emea.gs.com", excluded)[0]  # employer (subdomain)
    assert not match_custom("noatsign", excluded)[0]


def test_flag_custom_email_frame():
    df = pd.DataFrame({"EMAIL_ADDR": ["a@gmail.com", "b@bespoke-domain.co", "c@mac.com"]})
    out = flag_custom_email(df)
    # gmail excluded (free), mac.com excluded (premium), bespoke domain flagged.
    assert list(out["custom_email"]) == [False, True, False]
    assert out.loc[1, "custom_email_reason"] == "bespoke-domain.co"
