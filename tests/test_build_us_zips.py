"""scripts/build_us_zips.py — aggregating IRS SOI ZIP data into the us_zip reference list."""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_us_zips", Path(__file__).resolve().parents[1] / "scripts" / "build_us_zips.py")
buz = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(buz)

from scoring.signals.us_zip import load_zips


# IRS SOI shape: per ZIP, one row per income bracket. A00100 is AGI in $ THOUSANDS; N1 is returns.
SAMPLE = [
    {"STATE": "CA", "zipcode": "90210", "agi_stub": "5", "N1": "1000", "A00100": "300000"},
    {"STATE": "CA", "zipcode": "90210", "agi_stub": "6", "N1": "500",  "A00100": "450000"},  # -> mean 500k
    {"STATE": "NY", "zipcode": "10021", "agi_stub": "6", "N1": "800",  "A00100": "480000"},  # -> mean 600k
    {"STATE": "TX", "zipcode": "75001", "agi_stub": "6", "N1": "1000", "A00100": "120000"},  # mean 120k -> out
    {"STATE": "CA", "zipcode": "94027", "agi_stub": "6", "N1": "50",   "A00100": "100000"},  # <100 returns -> out
    {"STATE": "XX", "zipcode": "99999", "agi_stub": "6", "N1": "9999", "A00100": "9990000"}, # aggregate row -> skip
    {"STATE": "CA", "zipcode": "0",     "agi_stub": "6", "N1": "9999", "A00100": "9990000"}, # state total -> skip
]


def test_aggregate_and_select():
    agg = buz.aggregate_irs(SAMPLE)
    assert agg["90210"]["returns"] == 1500 and agg["90210"]["agi_k"] == 750000
    assert "99999" not in agg and "0" not in agg              # aggregate rows dropped
    sel = buz.select_high_income(agg, min_agi=250_000, min_returns=100)
    assert set(sel) == {"90210", "10021"}                     # 75001 too low, 94027 too few returns
    assert sel["90210"] == (500000, "CA") and sel["10021"] == (600000, "NY")


def test_merge_preserves_curated_names():
    existing = {"10021": "Upper East Side NY", "10007": "Tribeca NY"}   # curated
    selected = {"90210": (500000, "CA"), "10021": (600000, "NY")}
    rows = buz.merge_rows(existing, selected, keep_existing=True)
    assert rows["10021"] == ("Upper East Side NY", "600000")  # curated name kept, mean set
    assert rows["90210"] == ("CA", "500000")                  # new ZIP: state label
    assert rows["10007"] == ("Tribeca NY", "")                # curated-only row untouched
    # --no-merge drops the curated-only rows
    replaced = buz.merge_rows(existing, selected, keep_existing=False)
    assert "10007" not in replaced and set(replaced) == {"90210", "10021"}


def test_write_is_loadable_by_the_signal(tmp_path):
    out = tmp_path / "us_hnwi_zips.csv"
    rows = buz.merge_rows({}, buz.select_high_income(buz.aggregate_irs(SAMPLE), 250_000, 100), keep_existing=False)
    buz.write_table(out, [], rows)
    zips = load_zips(out)                                      # the live signal reads it back
    assert set(zips) == {"90210", "10021"}
    assert zips["10021"] == "NY"                               # area label round-trips
