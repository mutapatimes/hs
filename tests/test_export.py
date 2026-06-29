"""Tests for the spreadsheet export."""
import openpyxl
import pandas as pd

from scoring.combine import HIDDEN_COL, SCORE_COL, score_customers
from scoring.export import export_scored


def _frame():
    base = {
        "Name": "x", "Spent": 0, "SEGMENT": "Final Client",
        "EMAIL_ADDR": "x@gmail.com", "PHONE": "07000 000000",
        "COMPANY_NAME": None, "LATEST_BILLING_ZIP": "E14 9GU",
        "LATEST_BILLING_ADDRESS1": "1 Nowhere Road",
        "LATEST_BILLING_ADDRESS3": "London", "LATEST_BILLING_ADDRESS4": "United Kingdom",
        "LATEST_SHIPPING_ADDRESS1": "1 Nowhere Road", "LATEST_SHIPPING_ADDRESS3": "London",
        "LATEST_SHIPPING_ADDRESS4": "United Kingdom", "LATEST_SHIPPING_ZIP": "E14 9GU",
    }
    rows = [
        {**base, "Name": "Hidden Big", "Spent": 4000, "LATEST_BILLING_ZIP": "SW10 9SJ"},
        {**base, "Name": "Hidden Small", "Spent": 10, "LATEST_BILLING_ADDRESS4": "Qatar"},
        {**base, "Name": "Above Threshold", "Spent": 8000, "LATEST_BILLING_ZIP": "SW10 9SJ"},
        {**base, "Name": "No Signal", "Spent": 100},
    ]
    return pd.DataFrame(rows)


def test_export_creates_workbook_with_three_sheets(tmp_path):
    path = export_scored(df=_frame(), path=tmp_path / "out.xlsx")
    assert path.exists()
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Hidden VICs", "Above threshold", "Signal summary"]


def test_hidden_sheet_is_below_threshold_and_ranks_by_score(tmp_path):
    path = export_scored(df=_frame(), path=tmp_path / "out.xlsx")
    hidden = pd.read_excel(path, sheet_name="Hidden VICs")

    names = hidden["Name"].tolist()
    assert "Above Threshold" not in names   # already spends above the cutoff -> excluded
    assert "No Signal" not in names         # nothing fired -> excluded
    # Hidden Big (postcode, weight 3) ranks above Hidden Small (GCC, weight 2)
    assert names == ["Hidden Big", "Hidden Small"]


def test_above_threshold_sheet_holds_the_big_spender(tmp_path):
    path = export_scored(df=_frame(), path=tmp_path / "out.xlsx")
    known = pd.read_excel(path, sheet_name="Above threshold")
    assert known["Name"].tolist() == ["Above Threshold"]
