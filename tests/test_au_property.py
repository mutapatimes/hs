"""Australia home-value signal (NSW VG): table load, the country gate, and the ingest script."""
import csv
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd

from scoring.signals import au_property


def _table():
    return {
        "2027": {"tier": "ultra", "area": "Point Piper & Darling Point"},
        "2095": {"tier": "prime", "area": "Manly"},
        "2041": {"tier": "high", "area": "Balmain"},
    }


def test_seed_table_loads_and_is_valid():
    table = au_property.load_values()
    assert "2027" in table and table["2027"]["tier"] == "ultra"
    assert "3142" in table and table["3142"]["tier"] == "ultra"   # Toorak: curated non-NSW row
    assert "6011" in table                                        # Peppermint Grove (WA)
    assert all(v["tier"] in {"ultra", "prime", "high"} for v in table.values())


def test_country_gate_is_positive_only():
    """2027 is Point Piper AND a Norwegian rural code: a match needs the country to SAY Australia."""
    t = _table()
    assert au_property.match_pc("2027", "Australia", t)[0] is True
    assert au_property.match_pc("2027", "AU", t)[0] is True
    assert au_property.match_pc("NSW 2027", "australia", t)[0] is True   # digits extracted
    assert au_property.match_pc("2027", "Norway", t)[0] is False
    assert au_property.match_pc("2027", "Austria", t)[0] is False        # not a prefix match
    assert au_property.match_pc("2027", None, t)[0] is False             # no country -> never fires
    assert au_property.match_pc("2027", "", t)[0] is False


def test_reason_is_a_grade_never_a_price():
    hit, tier, reason = au_property.match_pc("2095", "australia", _table())
    assert hit and tier == "prime" and reason == "Prime (Manly)"
    assert "$" not in reason and "AUD" not in reason


def test_flag_pairs_each_postcode_with_its_own_country():
    df = pd.DataFrame({
        "LATEST_BILLING_ZIP": ["2027", "2027", None, "2041"],
        "LATEST_BILLING_ADDRESS4": ["Australia", "Norway", None, "australia"],
        "LATEST_SHIPPING_ZIP": [None, "2095", "2095", "2027"],
        "LATEST_SHIPPING_ADDRESS4": [None, "Australia", "Denmark", "United Kingdom"],
    })
    out = au_property.flag_au_property(df, table=_table())
    # row 0: billing Australia -> ultra. row 1: billing gated out, shipping -> prime.
    # row 2: shipping Denmark -> nothing. row 3: billing high; UK shipping gated out.
    assert list(out[au_property.FLAG_COL]) == [True, True, False, True]
    assert list(out[au_property.TIER_COL]) == ["ultra", "prime", None, "high"]


def _b_record(postcode, locality, price, strata="", nature="R", purpose="RESIDENCE"):
    parts = [""] * 24
    parts[0] = "B"
    parts[9], parts[10], parts[15] = locality, postcode, str(price)
    parts[17], parts[18], parts[19] = nature, purpose, strata
    return ";".join(parts)


def test_build_script_aggregates_psi_zip(tmp_path):
    """The ingest walks a nested PSI zip into tiered AUD medians, merging curated rows."""
    lines = []
    lines += [_b_record("2088", "MOSMAN", 5_500_000)] * 25            # -> ultra
    lines += [_b_record("2170", "LIVERPOOL", 900_000)] * 25           # below every band -> dropped
    lines += [_b_record("2108", "PALM BEACH", 5_000_000)] * 10        # too few sales -> dropped
    lines += [_b_record("2088", "MOSMAN", 800_000, strata="12")] * 25  # units never counted
    lines += [_b_record("2088", "MOSMAN", 4_000_000, nature="V", purpose="VACANT LAND")] * 25
    inner = tmp_path / "week.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("001_SALES.DAT", "\r\n".join(lines) + "\r\n")
    outer = tmp_path / "2025.zip"
    with zipfile.ZipFile(outer, "w") as zf:                            # yearly = zip of zips
        zf.write(inner, "week.zip")
    out = tmp_path / "au.csv"
    out.write_text("postcode,area,median_aud,tier\n3142,Toorak,5400000,ultra\n")  # curated VIC
    r = subprocess.run([sys.executable, "scripts/build_au_property.py",
                        "--files", str(outer), "--out", str(out)],
                       capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0, r.stderr
    rows = {row[0]: row for row in csv.reader(out.open())
            if row and not row[0].startswith("#") and row[0] != "postcode"}
    assert rows["2088"][3] == "ultra" and rows["2088"][1] == "Mosman"
    assert "2170" not in rows and "2108" not in rows
    assert rows["3142"][3] == "ultra"     # curated Toorak row survived the merge
