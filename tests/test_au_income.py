"""Australia income signal (ATO): table load, the country gate, and the ingest script."""
import csv
import subprocess
import sys
from pathlib import Path

import openpyxl
import pandas as pd

from scoring.signals import au_income


def _table():
    return {
        "3142": {"tier": "ultra", "area": "Toorak & Hawksburn"},
        "2041": {"tier": "prime", "area": "Balmain"},
        "2039": {"tier": "high", "area": "Rozelle"},
    }


def test_baked_table_loads_and_is_valid():
    table = au_income.load_values()
    assert "3142" in table and table["3142"]["tier"] == "ultra"   # Toorak
    assert "3944" in table and table["3944"]["tier"] == "ultra"   # Portsea: the national top
    assert "6011" in table                                        # Peppermint Grove (WA)
    assert all(v["tier"] in {"ultra", "prime", "high"} for v in table.values())
    assert len(table) > 50                                        # national coverage


def test_country_gate_is_positive_only():
    t = _table()
    assert au_income.match_pc("3142", "Australia", t)[0] is True
    assert au_income.match_pc("3142", "AUS", t)[0] is True
    assert au_income.match_pc("3142", "Austria", t)[0] is False
    assert au_income.match_pc("3142", "Norway", t)[0] is False
    assert au_income.match_pc("3142", None, t)[0] is False
    assert au_income.match_pc("3142", "", t)[0] is False


def test_reason_is_a_grade_never_a_figure():
    hit, tier, reason = au_income.match_pc("2041", "australia", _table())
    assert hit and tier == "prime" and reason == "High-income area (Balmain)"
    assert "$" not in reason and "income of" not in reason.lower()


def test_flag_pairs_each_postcode_with_its_own_country():
    df = pd.DataFrame({
        "LATEST_BILLING_ZIP": ["3142", "3142", "2039"],
        "LATEST_BILLING_ADDRESS4": ["Australia", "Denmark", "australia"],
        "LATEST_SHIPPING_ZIP": [None, "2041", "3142"],
        "LATEST_SHIPPING_ADDRESS4": [None, "Australia", "Switzerland"],
    })
    out = au_income.flag_au_income(df, table=_table())
    assert list(out[au_income.FLAG_COL]) == [True, True, True]
    assert list(out[au_income.TIER_COL]) == ["ultra", "prime", "high"]


def _workbook(tmp_path, rows):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("Table 6B")
    ws.append(["Taxation statistics"])
    ws.append(["State", "SA4", "Postcode", "Individuals", "Taxable no.", "Taxable $"])
    for r in rows:
        ws.append(r)
    p = tmp_path / "ato.xlsx"
    wb.save(p)
    return p


def test_build_script_computes_averages_and_filters(tmp_path):
    src = _workbook(tmp_path, [
        ["VIC", "Melbourne - Inner", "3142", 10000, 1000, 282_000_000],  # avg 282k -> ultra
        ["NSW", "Sydney - Inner West", "2041", 11000, 1000, 170_000_000],  # avg 170k -> prime
        ["NSW", "Sydney - Blacktown", "2148", 30000, 1000, 65_000_000],   # below bands -> dropped
        ["NSW", "NSW other", "1001", 300, 600, 200_000_000],              # PO-box range -> dropped
        ["VIC", "Mornington Peninsula", "3944", 700, 100, 33_000_000],    # <500 earners -> dropped
    ])
    out = tmp_path / "au_income.csv"
    r = subprocess.run([sys.executable, "scripts/build_au_income.py",
                        "--files", str(src), "--out", str(out)],
                       capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert r.returncode == 0, r.stderr
    rows = {row[0]: row for row in csv.reader(out.open())
            if row and not row[0].startswith("#") and row[0] != "postcode"}
    assert rows["3142"][3] == "ultra"
    assert rows["3142"][1] == "Toorak & Hawksburn"   # locality borrowed from the property seed
    assert rows["2041"][3] == "prime"
    assert "2148" not in rows and "1001" not in rows and "3944" not in rows
