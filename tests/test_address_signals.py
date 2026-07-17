"""Tests for the international address signals and the billing+shipping scan."""
import pandas as pd

from scoring.signals.gcc_billing import flag_gcc_billing, load_gcc_countries
from scoring.signals.hnw_area import AREA_COL, MATCH_COL as AREA_MATCH, flag_hnw_area
from scoring.signals.hnwi_postcode import FLAG_COL as HNWI_FLAG, flag_hnwi_postcode
from scoring.signals.intl_postcode import flag_intl_postcode, load_postcodes, match_postcode
from scoring.signals.prime_residence import RESIDENCE_COL, flag_prime_residence
from scoring.signals.wealth_office import OFFICE_COL, flag_wealth_office


# --- address signals now scan BOTH billing and shipping ---------------------
def test_hnwi_postcode_matches_on_shipping_side():
    df = pd.DataFrame({"LATEST_BILLING_ZIP": ["E14 9GU"], "LATEST_SHIPPING_ZIP": ["SW1X 7DE"]})
    out = flag_hnwi_postcode(df)
    assert out[HNWI_FLAG].tolist() == [True]      # billing not prime, shipping is


def test_gcc_matches_on_shipping_country():
    countries = load_gcc_countries()
    df = pd.DataFrame({
        "LATEST_BILLING_ADDRESS4": ["United Kingdom"],
        "LATEST_SHIPPING_ADDRESS4": ["Qatar"],
    })
    out = flag_gcc_billing(df, countries)
    assert out["gcc_billing"].tolist() == [True]
    assert out["gcc_billing_country"].tolist() == ["Qatar"]


def test_prime_residence_matches_on_shipping_address():
    df = pd.DataFrame({
        "LATEST_BILLING_ADDRESS1": ["1 Ordinary Road"],
        "LATEST_SHIPPING_ADDRESS1": ["Apartment 5, One Hyde Park"],
    })
    out = flag_prime_residence(df)
    assert out["prime_residence_match"].tolist() == [True]
    assert out.loc[0, RESIDENCE_COL] == "One Hyde Park"


# --- HNW area (name-based, international) ------------------------------------
def test_hnw_area_matches_international_names_either_side():
    df = pd.DataFrame({
        "LATEST_BILLING_ADDRESS3": ["Roppongi", "Nowheresville"],
        "LATEST_SHIPPING_ADDRESS3": ["Nowheresville", "Gstaad"],
    })
    out = flag_hnw_area(df)
    assert out[AREA_MATCH].tolist() == [True, True]
    assert out.loc[0, AREA_COL] == "Roppongi"
    assert out.loc[1, AREA_COL] == "Gstaad"


# --- Wealth office ----------------------------------------------------------
def test_wealth_office_matches_building_in_the_right_city():
    df = pd.DataFrame({
        "LATEST_SHIPPING_ADDRESS1": ["30 Hudson Yards, Floor 70"],
        "LATEST_SHIPPING_ADDRESS3": ["New York"],
    })
    out = flag_wealth_office(df)
    assert out["wealth_office_match"].tolist() == [True]
    assert out.loc[0, OFFICE_COL] == "KKR"


def test_wealth_office_city_guard_rejects_same_street_other_city():
    # "21 Moorfields, London" IS Deutsche Bank; a Moorfields elsewhere is not.
    real = pd.DataFrame({"LATEST_BILLING_ADDRESS1": ["21 Moorfields"],
                         "LATEST_BILLING_ADDRESS3": ["London"]})
    assert flag_wealth_office(real).loc[0, OFFICE_COL] == "Deutsche Bank"
    # "4 Brookfield Place, Southampton" must NOT match Brookfield's HQ.
    fake = pd.DataFrame({"LATEST_BILLING_ADDRESS1": ["4 Brookfield Place"],
                         "LATEST_BILLING_ADDRESS3": ["Southampton"]})
    assert not flag_wealth_office(fake)["wealth_office_match"].any()


# --- International postcode (country-guarded) --------------------------------
def test_intl_postcode_country_guard_blocks_collision():
    rows = load_postcodes()
    # Tokyo 100-0001 (digits 1000001) and Beijing 100600 both start "100" — the
    # country guard must keep them apart.
    assert match_postcode("106-0032", "Japan", rows)[0]
    assert not match_postcode("106-0032", "China", rows)[0]      # right zip, wrong country
    assert match_postcode("100600", "China", rows)[0]
    assert match_postcode("75008", "France", rows)[0]
    assert not match_postcode("75008", "Germany", rows)[0]


def test_flag_intl_postcode_frame_uses_both_sides():
    df = pd.DataFrame({
        "LATEST_BILLING_ZIP": ["E14 9GU"],
        "LATEST_BILLING_ADDRESS4": ["United Kingdom"],
        "LATEST_SHIPPING_ZIP": ["8001"],
        "LATEST_SHIPPING_ADDRESS4": ["Switzerland"],
    })
    out = flag_intl_postcode(df)
    assert out["intl_postcode"].tolist() == [True]
    assert "Zurich" in str(out.loc[0, "intl_postcode_reason"])


def test_wealth_office_recognises_law_firm_addresses_with_city_guard():
    """Top law-firm offices signal a senior lawyer; the city guard blocks same-street collisions."""
    df = pd.DataFrame([
        {"LATEST_BILLING_ADDRESS1": "70 Kingsway", "LATEST_BILLING_ADDRESS2": "Africa House",
         "LATEST_BILLING_ADDRESS3": "London", "LATEST_BILLING_ZIP": "WC2B 6AH"},
        {"LATEST_SHIPPING_ADDRESS1": "125 Broad Street", "LATEST_SHIPPING_ADDRESS3": "New York",
         "LATEST_SHIPPING_ZIP": "10004"},
        {"LATEST_BILLING_ADDRESS1": "125 Broad Street", "LATEST_BILLING_ADDRESS3": "Bristol",
         "LATEST_BILLING_ZIP": "BS1 2AA"},   # right street, wrong city -> no match
    ])
    out = flag_wealth_office(df)
    assert out.loc[0, OFFICE_COL] == "Mishcon de Reya"
    assert out.loc[1, OFFICE_COL] == "Sullivan & Cromwell"
    assert out.loc[2, "wealth_office_match"] == False
