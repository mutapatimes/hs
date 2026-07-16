"""Robustness: empty/malformed books must score and render, not crash."""
import numpy as np
import pandas as pd

from scoring.combine import HIDDEN_COL, SCORE_COL, score_customers


def test_empty_book_scores_cleanly():
    # a header-only export (brand-new store, or a filtered export with no rows)
    e = pd.DataFrame([{"Name": "x", "Spent": 1, "Count of CUST_ID": 1}]).head(0)
    s = score_customers(e)
    assert len(s) == 0 and SCORE_COL in s.columns and HIDDEN_COL in s.columns


def test_truly_empty_frame():
    s = score_customers(pd.DataFrame())
    assert len(s) == 0 and HIDDEN_COL in s.columns


def test_empty_book_renders_dashboard():
    from build_mvp import dashboard_payload, render_payload
    e = pd.DataFrame([{"Name": "x", "Spent": 1, "EMAIL_ADDR": "a@b.c",
                       "Count of CUST_ID": 1, "Last Shopped": "2025-01-01"}]).head(0)
    p = dashboard_payload(score_customers(e))
    assert p["data"] == [] and p["stat_count"] == "0" and p["landscape"]["hidden"]["n"] == 0
    assert "__DATA__" not in render_payload(p)


def test_torture_data_does_not_crash():
    rows = [
        {}, {"Name": None, "EMAIL_ADDR": None},
        {"Name": "", "Spent": ""}, {"Name": "Ada", "Spent": "NaN-ish"},
        {"Name": "李明", "EMAIL_ADDR": "李@例子.com", "LATEST_BILLING_ZIP": "北京"},
        {"Name": "X" * 5000, "LATEST_BILLING_ZIP": "9" * 50},
        {"Name": "=cmd()|'/c calc'!A1", "EMAIL_ADDR": "b@t.com"},          # formula injection
        {"Name": "<script>alert(1)</script>", "EMAIL_ADDR": "x@y.com"},    # XSS-shaped
        {"Name": "Jane", "Spent": float("nan"), "Count of CUST_ID": float("inf")},
        {"Name": "Neg", "Spent": -5000},
    ]
    s = score_customers(pd.DataFrame(rows))
    assert len(s) == len(rows)
    assert np.isfinite(pd.to_numeric(s[SCORE_COL], errors="coerce").fillna(0)).all()


def test_scoring_is_deterministic():
    df = pd.DataFrame([{"Name": "Elon Musk", "LATEST_BILLING_ZIP": "90210", "PHONE": "+13105550100"},
                       {"Name": "Jane Doe", "EMAIL_ADDR": "j@goldmansachs.com"}])
    a = score_customers(df.copy())[SCORE_COL].fillna(-1).tolist()
    b = score_customers(df.copy())[SCORE_COL].fillna(-1).tolist()
    assert a == b
