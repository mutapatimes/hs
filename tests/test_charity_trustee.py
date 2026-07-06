"""Charity Commission trustee signal: matching + corroboration-only behaviour."""
from __future__ import annotations

import pandas as pd

from scoring.combine import score_customers
from scoring.signals import charity_trustee as ct


def _table():
    return {
        ct._normalize("Evelyn Aldenham"):
            "Evelyn Aldenham — trustee of The Aldenham Family Foundation (Charity Commission)",
        ct._normalize("Marcus Thornbury"):
            "Marcus Thornbury — trustee of Thornbury Charitable Trust (Charity Commission)",
    }


def test_exact_name_matches():
    hit, reason = ct.match_name("Evelyn Aldenham", _table())
    assert hit and "Aldenham" in reason


def test_case_and_punctuation_insensitive():
    table = _table()
    assert ct.match_name("evelyn  aldenham", table)[0]
    assert ct.match_name("EVELYN-ALDENHAM", table)[0]


def test_partial_or_extra_tokens_do_not_match():
    table = _table()
    assert not ct.match_name("Evelyn M Aldenham", table)[0]   # exact-normalized only
    assert not ct.match_name("Aldenham", table)[0]
    assert not ct.match_name("Evelyn Aldenhamson", table)[0]


def test_flag_adds_columns():
    df = pd.DataFrame({"Name": ["Evelyn Aldenham", "Someone Else"]})
    out = ct.flag_charity_trustee(df, table=_table())
    assert list(out[ct.FLAG_COL]) == [True, False]
    assert out.loc[0, ct.REASON_COL] and out.loc[1, ct.REASON_COL] is None


def test_missing_name_column_is_safe():
    out = ct.flag_charity_trustee(pd.DataFrame({"Email": ["a@b.com"]}), table=_table())
    assert list(out[ct.FLAG_COL]) == [False]


def test_seed_table_loads_inert_example():
    table = ct.load_trustees()
    assert ct._normalize("Ada Placeholder") in table          # the shipped fictional seed row


def test_corroboration_only_never_a_sole_basis():
    # Name matches the trustee register only (nothing else fires) -> gated off, not a hidden VIC.
    df = pd.DataFrame([{"Name": "Ada Placeholder", "Email": "a@gmail.com", "Spent": 10}])
    scored = score_customers(df)
    assert scored.loc[0, "signal_count"] == 0
    assert not scored.loc[0, "hidden_vic"]
    assert not scored.loc[0, ct.FLAG_COL]                     # flag suppressed for display consistency
