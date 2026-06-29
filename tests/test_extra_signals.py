"""Tests for the B/C signals: honorific, phone-country, company-keyword,
rich-list, and prime-residence. Values are grounded in real data where possible
(HRH Prince Salman Al Saud, +41, LAIRD & PARTNERS, Evgeny Chichvarkin)."""
import pandas as pd

from scoring.signals.company_keyword import load_keywords, match_company
from scoring.signals.honorific import load_titles, match_name as match_title
from scoring.signals.phone_country import load_codes, match_phone
from scoring.signals.prime_residence import (
    MATCH_COL as RES_MATCH,
    RESIDENCE_COL,
    flag_prime_residence,
)
from scoring.signals.rich_list import load_rich_list, match_name as match_rich


# --- Honorific ---
def test_honorific():
    titles = load_titles()
    assert match_title("HRH Prince Salman Al Saud", titles) == (True, "HRH")
    assert match_title("Sir Elton John", titles)[0]
    assert match_title("Mui Gek Baron", titles) == (False, None)   # Baron trailing
    assert match_title("Dr Michael Heuser", titles) == (False, None)  # Dr not listed
    assert match_title("Ran Yuxian", titles) == (False, None)


# --- Phone country ---
def test_phone_country():
    codes = load_codes()
    assert match_phone("+41 79 123 4567", codes) == (True, "Switzerland")
    assert match_phone("+377 98 76 54", codes) == (True, "Monaco")
    assert match_phone("0041 79 123", codes) == (True, "Switzerland")   # 00 -> +
    assert match_phone("07544 923684", codes) == (False, None)          # UK, no code
    assert match_phone("+44 20 7946 0000", codes) == (False, None)      # UK not listed


# --- Company keyword ---
def test_company_keyword():
    kws = load_keywords()
    assert match_company("LAIRD & PARTNERS", kws) == (True, "PARTNERS")
    assert match_company("Smith Family Office", kws) == (True, "FAMILY OFFICE")
    assert match_company("THREADS STYLING LTD", kws) == (False, None)
    assert match_company("CAPITALS CAFE", kws) == (False, None)         # CAPITALS != CAPITAL


# --- Rich list ---
def test_rich_list():
    people = load_rich_list()
    assert match_rich("Evgeny Chichvarkin", people)[0]
    assert match_rich("James Dyson", people)[0]
    assert match_rich("John Smith", people) == (False, None)
    assert match_rich("Evgeny", people) == (False, None)                # partial


# --- Prime residence (billing address) ---
def test_prime_residence():
    df = pd.DataFrame(
        {
            "LATEST_BILLING_ADDRESS1": ["Apartment 5, One Hyde Park", "12 Hyde Park Gate"],
            "LATEST_BILLING_ADDRESS3": ["London", "London"],
            "LATEST_BILLING_ADDRESS4": ["United Kingdom", "United Kingdom"],
            "LATEST_BILLING_ZIP": ["SW1X 7LJ", "SW7 5DH"],
        }
    )
    out = flag_prime_residence(df)
    assert out[RES_MATCH].tolist() == [True, False]   # "Hyde Park Gate" != "One Hyde Park"
    assert out.loc[0, RESIDENCE_COL] == "One Hyde Park"
