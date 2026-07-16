"""The US name-match signals only fire when the customer is independently pinned to the US."""
import pandas as pd

from scoring.signals._us_nexus import us_nexus_mask
from scoring.signals import us_foundation, us_insider


def test_nexus_mask_rules():
    df = pd.DataFrame([
        {"LATEST_BILLING_ZIP": "90210", "PHONE": "", "LATEST_BILLING_ADDRESS4": "US"},       # US
        {"LATEST_BILLING_ZIP": "SW1A 1AA", "PHONE": "+442079460000", "LATEST_BILLING_ADDRESS4": "UK"},  # UK
        {"LATEST_BILLING_ZIP": "20121", "PHONE": "", "LATEST_BILLING_ADDRESS4": "Italy"},     # EU 5-digit, vetoed
        {"LATEST_BILLING_ZIP": "", "PHONE": "+14155550100", "LATEST_BILLING_ADDRESS4": ""},   # US phone
        {"LATEST_BILLING_ZIP": "10005", "PHONE": "", "LATEST_BILLING_ADDRESS4": ""},          # US ZIP, no country
    ])
    assert list(us_nexus_mask(df)) == [True, False, False, True, True]


def test_mask_none_without_geo_columns():
    assert us_nexus_mask(pd.DataFrame([{"Name": "X"}])) is None   # nothing to judge -> ungated


def _table(tmp_path):
    p = tmp_path / "ins.csv"
    p.write_text("name,tier,company\nCornelius Vanderbilt,owner,Acme\n", encoding="utf-8")
    return us_insider.load_insiders(p)


def test_insider_gated_by_us_nexus(tmp_path):
    t = _table(tmp_path)
    df = pd.DataFrame([
        {"Name": "Cornelius Vanderbilt", "LATEST_BILLING_ZIP": "10021", "LATEST_BILLING_ADDRESS4": "US"},
        {"Name": "Cornelius Vanderbilt", "LATEST_BILLING_ZIP": "W1K 1QA", "LATEST_BILLING_ADDRESS4": "United Kingdom"},
    ])
    res = us_insider.flag_us_insider(df, t)
    assert list(res["us_insider"]) == [True, False]
    assert res["us_insider_reason"][1] is None and res["us_insider_tier"][1] is None   # suppressed cleanly


def test_foundation_gated_by_us_nexus(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("name,foundation\nCornelia Vanderbilt,Vanderbilt Family Foundation\n", encoding="utf-8")
    t = us_foundation.load_trustees(p)
    df = pd.DataFrame([
        {"Name": "Cornelia Vanderbilt", "PHONE": "+12125550100"},              # US phone -> fires
        {"Name": "Cornelia Vanderbilt", "PHONE": "+33123456789"},              # FR phone -> suppressed
    ])
    res = us_foundation.flag_us_foundation(df, t)
    assert list(res["us_foundation"]) == [True, False]


def test_name_only_frame_stays_ungated(tmp_path):
    # a frame with no geo columns (e.g. a unit fixture) must still fire on the name alone
    t = _table(tmp_path)
    res = us_insider.flag_us_insider(pd.DataFrame([{"Name": "Cornelius Vanderbilt"}]), t)
    assert bool(res["us_insider"][0])
