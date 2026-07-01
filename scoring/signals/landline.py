"""UK landline signal.

Flags customers whose phone is a UK geographic landline (national prefix 01 or 02)
rather than a mobile (07) or a non-geographic line. A landline is a soft, positive
tell — it skews toward an established household or a commercial / office address, and
these days fewer people give one at all, so providing one is mildly informative.

It reads line TYPE only; the specific area code is NOT used, so this is not a
location / origin signal — just "is this a fixed line". Low weight (a supporting tell).
"""
from __future__ import annotations

import re

import pandas as pd

FLAG_COL = "landline"
REASON_COL = "landline_reason"


def _uk_national(value: object) -> str:
    """Best-effort UK national form: digits only, +44/0044 -> leading 0."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    d = re.sub(r"\D", "", str(value))
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("44"):
        d = "0" + d[2:]           # +44 20 7946 0018 -> 02079460018
    return d


def _is_landline(value: object) -> bool:
    d = _uk_national(value)
    return d.startswith("01") or d.startswith("02")


def flag_landline(df: pd.DataFrame, phone_col: str = "PHONE") -> pd.DataFrame:
    """Add landline flag + reason. Dormant if the phone column is absent."""
    out = df.copy()
    if phone_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    hits = out[phone_col].apply(_is_landline)
    out[FLAG_COL] = hits
    out[REASON_COL] = ["UK landline (not a mobile)" if h else None for h in hits]
    return out
