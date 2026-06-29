"""Tests for the heritage-surname (wealth-dynasty) signal."""
import pandas as pd

from scoring.combine import COUNT_COL, SCORE_COL, score_customers
from scoring.signals.heritage_surname import (
    flag_heritage_surname,
    load_surnames,
    match_name,
)


def test_distinctive_dynasty_surnames_match():
    s = load_surnames()
    assert match_name("Anne Vanderbilt", s)[0]
    assert match_name("Jacob Rothschild", s)[0]
    assert "Guggenheim" in str(match_name("Peggy Guggenheim", s)[1])


def test_plain_and_common_surnames_do_not_match():
    s = load_surnames()
    assert match_name("John Smith", s) == (False, None)
    # Common surnames are excluded by design (collisions / regressed to mean).
    assert match_name("Charlotte Spencer", s) == (False, None)
    assert match_name("James Howard", s) == (False, None)
    assert match_name("", s) == (False, None)


def test_flag_frame_and_missing_column():
    df = pd.DataFrame({"Name": ["A. Astor", "Jo Bloggs"]})
    out = flag_heritage_surname(df)
    assert out["heritage_surname"].tolist() == [True, False]
    assert not flag_heritage_surname(pd.DataFrame({"x": [1]}))["heritage_surname"].any()


def test_scores_low_and_groups_with_other_name_signals():
    # A dynasty surname alone: a weak (weight-1) flag, enough to surface a low spender.
    out = score_customers(pd.DataFrame([{
        "Name": "Cornelius Vanderbilt", "Spent": 100, "EMAIL_ADDR": "c@gmail.com",
        "LATEST_BILLING_ZIP": "LS1 1AA",
    }]))
    assert out.loc[0, COUNT_COL] == 1
    assert out.loc[0, SCORE_COL] == 1          # floor weight

    # rich_list + heritage_surname both fire -> grouped, so they DON'T stack to 2.
    out2 = score_customers(pd.DataFrame([{
        "Name": "James Dyson Vanderbilt", "Spent": 100,   # Dyson (rich_list) + Vanderbilt
        "EMAIL_ADDR": "x@gmail.com", "LATEST_BILLING_ZIP": "LS1 1AA",
    }]))
    assert out2.loc[0, COUNT_COL] == 2
    assert out2.loc[0, SCORE_COL] == 1.5       # 1 + 1*0.5 (name group diminishing)
