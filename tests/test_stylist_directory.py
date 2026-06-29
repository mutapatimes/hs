"""Broad stylist-directory signal (Tier 2) + its corroboration-only behavior."""
import pandas as pd

from scoring.combine import SUPPORTING_SIGNALS, score_customers
from scoring.signals.stylist_directory import (
    FLAG_COL,
    flag_stylist_directory,
    load_directory,
)

PEOPLE = [("EMILY LEE", "Emily Lee"), ("ANNA TREVELYAN", "Anna Trevelyan")]


def test_flag_matches_whole_name():
    out = flag_stylist_directory(pd.DataFrame({"Name": ["Emily Lee", "Nobody Here"]}),
                                 people=PEOPLE)
    assert out[FLAG_COL].tolist() == [True, False]


def test_registered_as_supporting():
    # Must be corroboration-only so common names never surface a customer alone.
    assert "stylist_directory" in SUPPORTING_SIGNALS


def test_directory_only_does_not_surface():
    # A bare directory name with no other signal contributes nothing.
    s = score_customers(pd.DataFrame([{"Name": "Rachel Zoe", "EMAIL_ADDR": "rz@gmail.com",
                                       "Spent": 300}]))
    assert s.iloc[0]["signal_count"] == 0


def test_directory_corroborates_when_another_signal_fires():
    s = score_customers(pd.DataFrame([{"Name": "Rachel Zoe",
                                       "EMAIL_ADDR": "rz@goldmansachs.com", "Spent": 300}]))
    row = s.iloc[0]
    assert row["signal_count"] >= 2 and "Possible stylist" in row["reasons"]


def test_real_directory_loads_and_excludes_curated():
    people = load_directory()
    names = {d for _, d in people}
    assert len(people) > 100
    assert "Law Roach" not in names  # curated Tier-1 names are excluded
