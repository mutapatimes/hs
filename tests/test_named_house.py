"""Named-house signal: a street line that is a NAMED property, not a numbered address."""
from __future__ import annotations

import pandas as pd

from scoring.combine import score_customers
from scoring.signals import named_house as nh


def _flag(lines, col="LATEST_BILLING_ADDRESS1"):
    return nh.flag_named_house(pd.DataFrame({col: lines}))


def test_named_estates_fire():
    out = _flag(["The Old Rectory, Church Lane", "Whitfield Manor", "Bletchingley Grange",
                 "The Old Vicarage", "Stanmore Priory"])
    assert out[nh.FLAG_COL].all()
    assert out.loc[0, nh.REASON_COL] == 'Named property: "The Old Rectory"'


def test_prefix_form_chalet_villa_chateau():
    out = _flag(["Chalet Eugenia", "Villa Serena", "Château Margaux"])   # accent-folded
    assert out[nh.FLAG_COL].all()


def test_street_names_and_numbers_do_not_fire():
    out = _flag(["Manor Road", "12 Manor Road", "Hall Lane", "Grange Avenue",
                 "Villa Road", "1 Abbey Street", "Priory Close"])
    assert not out[nh.FLAG_COL].any()


def test_apartments_and_bare_keywords_do_not_fire():
    out = _flag(["Flat 3, Priory Court", "Apartment 2, The Old Rectory", "Manor",
                 "Unit 5 Castle", "Suite 12, Grosvenor Hall"])
    assert not out[nh.FLAG_COL].any()


def test_shipping_and_second_line_also_checked():
    out = nh.flag_named_house(pd.DataFrame([
        {"LATEST_SHIPPING_ADDRESS1": "The Old Rectory"},
        {"LATEST_BILLING_ADDRESS2": "Whitfield Manor"},
    ]))
    assert out[nh.FLAG_COL].all()


def test_missing_columns_are_safe():
    out = nh.flag_named_house(pd.DataFrame({"Email": ["a@b.com"]}))
    assert list(out[nh.FLAG_COL]) == [False]


def test_scores_as_core_geo_signal():
    # A named house alone is a CORE signal (weight 2): counts and can surface a customer.
    df = pd.DataFrame([{"Name": "A", "Spent": 100,
                        "LATEST_BILLING_ADDRESS1": "The Old Rectory, Church Lane"}])
    scored = score_customers(df)
    assert scored.loc[0, nh.FLAG_COL]
    assert scored.loc[0, "signal_count"] >= 1
    assert "Named property" in scored.loc[0, "reasons"]


def test_institutional_halls_do_not_fire():
    out = _flag(["Town Hall", "The Village Hall", "International Hall",
                 "St Mary Church Hall", "Masonic Lodge"])
    assert not out[nh.FLAG_COL].any()
