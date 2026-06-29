"""Fashion-stylist name-match signal."""
import pandas as pd

from scoring.signals.fashion_stylist import FLAG_COL, REASON_COL, flag_fashion_stylist

PEOPLE = [("LAW ROACH", "Law Roach"), ("KATE YOUNG", "Kate Young"),
          ("JULIAN RIOS", "Julian Ríos")]


def test_matches_whole_name():
    df = pd.DataFrame({"Name": ["Law Roach", "Ms Kate Young", "Random Person"]})
    out = flag_fashion_stylist(df, people=PEOPLE)
    assert out[FLAG_COL].tolist() == [True, True, False]
    assert "Law Roach" in out[REASON_COL][0] and "verify" in out[REASON_COL][0]


def test_accent_insensitive():
    out = flag_fashion_stylist(pd.DataFrame({"Name": ["Julian Rios"]}), people=PEOPLE)
    assert bool(out[FLAG_COL][0])


def test_no_partial_match():
    # "Roach" alone (a surname fragment) should not match "Law Roach".
    out = flag_fashion_stylist(pd.DataFrame({"Name": ["John Roach"]}), people=PEOPLE)
    assert not out[FLAG_COL][0]


def test_missing_name_column():
    out = flag_fashion_stylist(pd.DataFrame({"EMAIL_ADDR": ["a@b.com"]}), people=PEOPLE)
    assert not out[FLAG_COL][0]


def test_real_reference_loads():
    from scoring.signals.fashion_stylist import load_stylists
    people = load_stylists()
    names = {d for _, d in people}
    assert "Law Roach" in names and "Mel Ottenberg" in names and len(people) > 50
