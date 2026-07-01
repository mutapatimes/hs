"""Companies House control signal: matching + corroboration-only behaviour."""
from __future__ import annotations

import pandas as pd

from scoring.combine import score_customers
from scoring.signals import companies_house as ch


def _table():
    return {
        ch._normalize("Anne Boden"): "Anne Boden — Founder & Director (Companies House)",
        ch._normalize("Tom Blomfield"): "Tom Blomfield — PSC (Companies House)",
    }


def test_exact_name_matches():
    table = _table()
    hit, reason = ch.match_name("Anne Boden", table)
    assert hit and "Anne Boden" in reason


def test_case_and_punctuation_insensitive():
    table = _table()
    assert ch.match_name("anne  boden", table)[0]
    assert ch.match_name("ANNE-BODEN", table)[0]


def test_partial_or_extra_tokens_do_not_match():
    table = _table()
    # exact-normalized match: a middle name or surname-only must NOT match
    assert not ch.match_name("Anne M Boden", table)[0]
    assert not ch.match_name("Boden", table)[0]
    assert not ch.match_name("Anne Bodenham", table)[0]


def test_flag_adds_columns():
    df = pd.DataFrame({"Name": ["Anne Boden", "Someone Else"]})
    out = ch.flag_companies_house(df, table=_table())
    assert list(out[ch.FLAG_COL]) == [True, False]
    assert out.loc[0, ch.REASON_COL] and out.loc[1, ch.REASON_COL] is None


def test_missing_name_column_is_safe():
    out = ch.flag_companies_house(pd.DataFrame({"Email": ["a@b.com"]}), table=_table())
    assert list(out[ch.FLAG_COL]) == [False]


def test_seed_table_loads():
    table = ch.load_controllers()
    assert ch._normalize("James Dyson") in table


def test_corroboration_only_never_a_sole_basis():
    # Name matches CH only (nothing else fires) -> gated off, not a hidden VIC.
    df = pd.DataFrame([{"Name": "Anne Boden", "Email": "a@gmail.com", "Spent": 10}])
    scored = score_customers(df)
    assert scored.loc[0, "signal_count"] == 0
    assert not scored.loc[0, "hidden_vic"]
    assert not scored.loc[0, ch.FLAG_COL]  # flag suppressed for display consistency


def test_counts_when_a_core_signal_also_fires():
    # CH + a prime postcode -> CH now corroborates and is counted.
    df = pd.DataFrame([{"Name": "Anne Boden", "Email": "a@gmail.com",
                        "Spent": 10, "LATEST_BILLING_ZIP": "SW10 9SJ"}])
    scored = score_customers(df)
    assert scored.loc[0, ch.FLAG_COL]
    assert "Companies House" in scored.loc[0, "reasons"]
    assert scored.loc[0, "hidden_vic"]
