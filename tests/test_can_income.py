"""Canada FSA income signal (CRA): table load, the country gate, and the ingest script."""
import csv
import subprocess
import sys
from pathlib import Path

import pandas as pd

from scoring.signals import can_income


def _table():
    return {
        "M4W": {"tier": "ultra", "area": "Rosedale, Toronto"},
        "V7S": {"tier": "prime", "area": "British Properties, West Vancouver"},
        "H2V": {"tier": "high", "area": "Outremont, Montreal"},
    }


def test_baked_table_loads_and_is_valid():
    table = can_income.load_values()
    assert table["M4W"]["tier"] == "ultra"           # Rosedale
    assert table["H3Y"]["tier"] == "ultra"           # Westmount
    assert "V7V" in table and "L6J" in table         # West Vancouver, Old Oakville
    assert all(v["tier"] in {"ultra", "prime", "high"} for v in table.values())
    assert len(table) > 40                           # national coverage


def test_country_gate_and_fsa_extraction():
    t = _table()
    assert can_income.match_pc("M4W 1A5", "Canada", t)[0] is True
    assert can_income.match_pc("m4w1a5", "CA", t)[0] is True
    assert can_income.match_pc("M4W", "canada", t)[0] is True     # bare FSA
    # W1A-style UK outcodes share the letter-digit-letter shape: the gate must hold.
    assert can_income.match_pc("M4W 1A5", "United Kingdom", t)[0] is False
    assert can_income.match_pc("M4W 1A5", None, t)[0] is False
    assert can_income.match_pc("M4W 1A5", "", t)[0] is False
    # a 5-char fragment is not a postal code
    assert can_income.match_pc("M4W1A", "Canada", t)[0] is False


def test_reason_is_a_grade_never_a_figure():
    hit, tier, reason = can_income.match_pc("V7S 2K9", "canada", _table())
    assert hit and tier == "prime"
    assert reason == "High-income area (British Properties, West Vancouver)"
    assert "$" not in reason


def test_flag_pairs_each_code_with_its_own_country():
    df = pd.DataFrame({
        "LATEST_BILLING_ZIP": ["M4W 1A5", "M4W 1A5", "H2V 4E9"],
        "LATEST_BILLING_ADDRESS4": ["Canada", "United Kingdom", "canada"],
        "LATEST_SHIPPING_ZIP": [None, "V7S 2K9", "M4W 1A5"],
        "LATEST_SHIPPING_ADDRESS4": [None, "Canada", "France"],
    })
    out = can_income.flag_can_income(df, table=_table())
    assert list(out[can_income.FLAG_COL]) == [True, True, True]
    assert list(out[can_income.TIER_COL]) == ["ultra", "prime", "high"]


def test_build_script_computes_averages_and_filters(tmp_path):
    src = tmp_path / "cra.csv"
    with src.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Prov/Terr", "FSA", "Total", "Total income", "Net income"])
        w.writerow(["35", "M4W", "12000", "2916000", "x"])   # 2.916B/12k = 243k -> ultra
        w.writerow(["35", "L6J", "20000", "3200000", "x"])   # 160k -> prime
        w.writerow(["35", "M1B", "30000", "1200000", "x"])   # 40k -> below bands
        w.writerow(["35", "K1P", "700", "1030000", "x"])     # office FSA, <2500 filers -> dropped
    out = tmp_path / "can.csv"
    r = subprocess.run([sys.executable, "scripts/build_can_income.py",
                        "--files", str(src), "--out", str(out)],
                       capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0, r.stderr
    rows = {row[0]: row for row in csv.reader(out.open())
            if row and not row[0].startswith("#") and row[0] != "fsa"}
    assert rows["M4W"][3] == "ultra" and rows["M4W"][1] == "Rosedale, Toronto"
    assert rows["L6J"][3] == "prime"
    assert "M1B" not in rows and "K1P" not in rows
