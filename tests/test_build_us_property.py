"""scripts/build_us_property.py — Zillow ZHVI ZIP data -> the us_property reference table + signal."""
import csv
import importlib.util
import io
from pathlib import Path

import pandas as pd

_SPEC = importlib.util.spec_from_file_location(
    "build_us_property", Path(__file__).resolve().parents[1] / "scripts" / "build_us_property.py")
bup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bup)

from scoring.signals.us_property import flag_us_property, load_values

# Zillow ZIP ZHVI shape: RegionName is the ZIP; wide monthly value columns; latest = last non-empty.
SAMPLE_CSV = (
    "RegionID,SizeRank,RegionName,RegionType,StateName,State,City,Metro,CountyName,2026-04-30,2026-05-31\n"
    "1,1,94027,zip,CA,CA,Atherton,SF Bay,San Mateo,8000000,8305049\n"      # ultra (>= $2M)
    "2,2,10021,zip,NY,NY,New York,NYC,New York,1500000,\n"                  # prime; latest blank -> use Apr
    "3,3,75001,zip,TX,TX,Addison,Dallas,Dallas,395000,400000\n"            # < $1M -> dropped
)


def _rows():
    return bup.build(csv.DictReader(io.StringIO(SAMPLE_CSV)), min_value=1_000_000)


def test_latest_value_and_tiering():
    rows = _rows()
    assert set(rows) == {"94027", "10021"}                      # 75001 below threshold, dropped
    assert rows["94027"] == ("Atherton CA", 8305049, "ultra")
    assert rows["10021"] == ("New York NY", 1500000, "prime")   # fell back to the last non-empty month


def test_min_value_is_configurable():
    rows = bup.build(csv.DictReader(io.StringIO(SAMPLE_CSV)), min_value=300_000)
    assert "75001" in rows and rows["75001"][2] == "prime"      # now above the lowered floor


def test_write_round_trips_through_the_signal(tmp_path):
    out = tmp_path / "us_property_values.csv"
    bup.write_table(out, _rows())
    table = load_values(out)                                    # the live signal reads it back
    assert table["94027"] == {"tier": "ultra", "area": "Atherton CA"}
    df = pd.DataFrame([{"LATEST_BILLING_ZIP": "94027"}, {"LATEST_BILLING_ZIP": "99999"}])
    res = flag_us_property(df, table)
    assert bool(res["us_property"][0]) and res["us_property_tier"][0] == "ultra"
    assert res["us_property_reason"][0] == "Ultra-prime (Atherton CA)"   # a GRADE, never the $ price
    assert not bool(res["us_property"][1])
