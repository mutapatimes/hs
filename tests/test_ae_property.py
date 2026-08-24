"""UAE community signal (DLD): name matching, country gate, and the ingest script."""
import csv
import subprocess
import sys
from pathlib import Path

import pandas as pd

from scoring.signals import ae_property


def _table():
    return ae_property.load_values()


def test_seed_table_loads_longest_first():
    t = _table()
    names = [r["name"] for r in t]
    assert "Emirates Hills" in names and "Dubai Marina" in names
    # longest-first so "Palm Jumeirah" cannot lose to a shorter contained name
    assert all(len(t[i]["needle"]) >= len(t[i + 1]["needle"]) for i in range(len(t) - 1))


def test_country_gate_and_whole_word_matching():
    t = _table()
    hit, tier, reason = ae_property.match_address(
        "Villa 12, Emirates Hills, Dubai", "United Arab Emirates", t)
    assert hit and tier == "ultra" and reason == "Ultra-prime (Emirates Hills)"
    # same text, wrong country -> gated out
    assert ae_property.match_address("Villa 12, Emirates Hills", "United States", t)[0] is False
    assert ae_property.match_address("Villa 12, Emirates Hills", None, t)[0] is False
    # a street merely containing a word from an area name never fires (whole-phrase match)
    assert ae_property.match_address("1 Hills Road, Deira", "UAE", t)[0] is False
    # accent/case folding
    assert ae_property.match_address("PALM JUMEIRAH, frond K", "uae", t)[0] is True


def test_flag_scans_both_sides_higher_tier_wins():
    df = pd.DataFrame({
        "LATEST_BILLING_ADDRESS1": ["Apt 4, Dubai Marina", "Business Bay tower", None],
        "LATEST_BILLING_ADDRESS4": ["United Arab Emirates", "France", None],
        "LATEST_SHIPPING_ADDRESS1": ["Villa 3, Palm Jumeirah", "Bluewaters Island", "The Lakes"],
        "LATEST_SHIPPING_ADDRESS4": ["UAE", "United Arab Emirates", "United Kingdom"],
    })
    out = ae_property.flag_ae_property(df)
    assert list(out[ae_property.FLAG_COL]) == [True, True, False]
    # row 0: marina high vs palm ultra -> ultra. row 1: billing gated (France), shipping ultra.
    assert list(out[ae_property.TIER_COL]) == ["ultra", "ultra", None]


def test_build_script_aggregates_and_aliases(tmp_path):
    src = tmp_path / "dld.csv"
    fields = ["trans_group_en", "property_usage_en", "area_name_en", "actual_worth", "procedure_area"]
    with src.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for _ in range(50):   # Marsa Dubai (cadastral) -> Dubai Marina alias, 20,000 AED/sqm -> prime
            w.writerow({"trans_group_en": "Sales", "property_usage_en": "Residential",
                        "area_name_en": "Marsa Dubai", "actual_worth": "2000000",
                        "procedure_area": "100"})
        for _ in range(50):   # below every band -> dropped
            w.writerow({"trans_group_en": "Sales", "property_usage_en": "Residential",
                        "area_name_en": "International City", "actual_worth": "500000",
                        "procedure_area": "100"})
        for _ in range(10):   # too few sales
            w.writerow({"trans_group_en": "Sales", "property_usage_en": "Residential",
                        "area_name_en": "Island 2", "actual_worth": "9000000",
                        "procedure_area": "200"})
        w.writerow({"trans_group_en": "Mortgages", "property_usage_en": "Residential",
                    "area_name_en": "Marsa Dubai", "actual_worth": "1", "procedure_area": "100"})
    out = tmp_path / "ae.csv"
    out.write_text("area,emirate,median_aed_sqm,tier\nSaadiyat Island,Abu Dhabi,,prime\n")
    r = subprocess.run([sys.executable, "scripts/build_ae_property.py",
                        "--files", str(src), "--out", str(out)],
                       capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0, r.stderr
    rows = {row[0]: row for row in csv.reader(out.open())
            if row and not row[0].startswith("#") and row[0] != "area"}
    assert rows["Dubai Marina"][3] == "prime"        # aliased from Marsa Dubai
    assert "International City" not in rows and "Island 2" not in rows
    assert rows["Saadiyat Island"][3] == "prime"     # curated Abu Dhabi row survived
