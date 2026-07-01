"""Shared-phone household/handler linkage signal (on by default, relationship structure)."""
import pandas as pd

from scoring.combine import ORIGIN_PROXY_SIGNALS, active_signals
from scoring.signals.shared_phone import FLAG_COL, REASON_COL, flag_shared_phone


def test_flags_repeated_numbers_only():
    df = pd.DataFrame({"PHONE": [
        "+44 7700 900111",   # same number as row 2 (different formatting) -> shared
        "07700 900222",      # unique
        "+447700900111",     # same digits as row 0                        -> shared
        "",                  # blank                                       -> no
        "123", "123",        # too short to be real                        -> no
    ]})
    out = flag_shared_phone(df)
    assert out[FLAG_COL].tolist() == [True, False, True, False, False, False]
    assert "shared with 1 other" in out[REASON_COL].tolist()[0]


def test_widely_shared_number_is_ignored():
    # A number on many records is a store default / switchboard, not a household.
    df = pd.DataFrame({"PHONE": ["020 7000 1234"] * 8})
    assert flag_shared_phone(df)[FLAG_COL].tolist() == [False] * 8


def test_dormant_without_phone_column():
    out = flag_shared_phone(pd.DataFrame({"x": [1, 2]}))
    assert out[FLAG_COL].tolist() == [False, False]
    assert out[REASON_COL].tolist() == [None, None]


def test_on_by_default_not_origin_proxy():
    assert "shared_phone" not in ORIGIN_PROXY_SIGNALS
    assert "shared_phone" in {s[0] for s in active_signals()}  # scores by default
