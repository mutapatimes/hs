"""Shared-phone household / handler linkage signal.

Flags customers whose phone number also appears on one or more OTHER customer
records in the same base. A repeated number is a relationship-structure tell — a
household, or an assistant / PA placing orders for a principal — not a location or
origin fact, so it runs by default. Pure identity linkage from data already held;
no external lookup, no protected-characteristic input.

Cross-row by nature: it counts how often each normalised number appears across the
whole customer frame, then flags every record on a number seen 2+ times.
"""
from __future__ import annotations

import re

import pandas as pd

FLAG_COL = "shared_phone"
REASON_COL = "shared_phone_reason"

_MIN_DIGITS = 7   # ignore blanks and junk too short to be a real number
_MAX_CLUSTER = 6  # a number on more records than this is a store default / switchboard,
                  # not a household — don't flag (avoids mass false positives on junk)


def _norm(value: object) -> str:
    """Digits only (leading international 00 dropped); '' if too short to be real."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    digits = re.sub(r"\D", "", str(value))
    if digits.startswith("00"):
        digits = digits[2:]
    return digits if len(digits) >= _MIN_DIGITS else ""


def flag_shared_phone(df: pd.DataFrame, phone_col: str = "PHONE") -> pd.DataFrame:
    """Add shared-phone flag + reason. Dormant if the phone column is absent."""
    out = df.copy()
    if phone_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    norm = out[phone_col].apply(_norm)
    counts = norm[norm != ""].value_counts()

    def _row(n: str):
        if not n:
            return False, None
        c = int(counts.get(n, 0))
        if c < 2 or c > _MAX_CLUSTER:  # unique, or a placeholder/switchboard shared too widely
            return False, None
        others = c - 1
        rec = "record" if others == 1 else "records"
        return True, f"Phone shared with {others} other customer {rec} (household or shared handler)"

    results = norm.apply(_row)
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
