"""Tests for the corroboration-only assistant/PA-order signal."""
import pandas as pd

from scoring.combine import COUNT_COL, HIDDEN_COL, score_customers
from scoring.signals.assistant_order import detect, flag_assistant_order


# --- detection --------------------------------------------------------------
def test_detects_co_address_pa_name_and_role_email():
    assert detect("Jane Doe", "x@gmail.com", "Lansdowne House | c/o John Smith")[0]
    assert detect("Sarah Jenkins (PA to CEO)", "s@x.com", "1 St")[0]
    assert detect("Mark Davis (EA)", "m@x.com", "1 St")[0]
    assert detect("Bob", "ea.to.md@firm.com", "1 St")[0]
    assert detect("Bob", "pa.team@firm.com", "1 St")[0]
    r = detect("Jane", "execoffice@firm.co.uk", "1 St")
    assert r[0] and "role email" in r[1]


def test_plain_orders_and_lookalike_emails_do_not_fire():
    assert detect("John Smith", "john@gmail.com", "1 Normal Road, London") == (False, None)
    assert detect("Paul Sean", "paul@gmail.com", "1 St") == (False, None)   # 'pa'/'ea' substrings
    assert detect("Papa Tortelli", "sean@x.com", "1 St") == (False, None)


def test_flag_frame_and_missing_columns():
    df = pd.DataFrame({"Name": ["Anne (EA)", "Jo Bloggs"], "EMAIL_ADDR": ["a@x.com", "jo@gmail.com"]})
    out = flag_assistant_order(df)
    assert out["assistant_order"].tolist() == [True, False]
    assert not flag_assistant_order(pd.DataFrame({"x": [1]}))["assistant_order"].any()


# --- corroboration gate -----------------------------------------------------
def _row(**kw):
    base = {"Name": "x", "Spent": 100, "EMAIL_ADDR": "x@gmail.com",
            "LATEST_BILLING_ZIP": "LS1 1AA", "LATEST_BILLING_ADDRESS4": "United Kingdom"}
    base.update(kw)
    return base


def test_assistant_order_alone_never_flags():
    # Role email on a FREE provider -> no other signal -> uncorroborated, hidden.
    # (A role email on a custom/corporate domain WOULD be corroborated by
    #  custom_email — which is the right read: an assistant at a real firm.)
    out = score_customers(pd.DataFrame([_row(EMAIL_ADDR="pa.team@gmail.com")]))
    assert out.loc[0, COUNT_COL] == 0
    assert not out.loc[0, HIDDEN_COL]


def test_assistant_order_counts_when_corroborated():
    # Assistant email AT a wealth-employer domain -> work_email corroborates it.
    out = score_customers(pd.DataFrame([_row(EMAIL_ADDR="pa.to.md@gs.com")]))  # gs.com = Goldman
    assert out.loc[0, COUNT_COL] == 2     # work_email + assistant_order
