"""Phone-country signal.

Flags customers whose phone number has an international dialling code that
correlates with wealth (reference_data/phone/hnw_dialing_codes.csv) — e.g.
Monaco (+377), Switzerland (+41), the Gulf. Matched by longest prefix, so
+1345 (Cayman) wins over +1.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import PHONE_CODES_FILE

FLAG_COL = "phone_country"
REASON_COL = "phone_country_reason"


def _normalize(value: object) -> str:
    """Return the phone as '+<digits>', converting a leading 00 to +."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    digits_plus = re.sub(r"[^0-9+]", "", str(value))
    if digits_plus.startswith("00"):
        digits_plus = "+" + digits_plus[2:]
    return digits_plus


def load_codes(path: Path | str = PHONE_CODES_FILE) -> list[tuple[str, str]]:
    """Read [(code, jurisdiction)], longest code first for prefix matching."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Phone-code reference list not found: {path}")
    codes: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            code = row[0].strip()
            if not code or code.startswith("#") or code == "code":
                continue
            jurisdiction = row[1].strip() if len(row) > 1 else code
            codes.append((code, jurisdiction))
    return sorted(codes, key=lambda c: -len(c[0]))


def match_phone(phone: object, codes: list[tuple[str, str]]) -> tuple[bool, str | None]:
    norm = _normalize(phone)
    if not norm.startswith("+"):
        return False, None
    for code, jurisdiction in codes:
        if norm.startswith(code):
            return True, jurisdiction
    return False, None


def flag_phone_country(df: pd.DataFrame, codes=None, phone_col: str = "PHONE"):
    """Add phone-country flag + jurisdiction columns to a copy of ``df``."""
    if codes is None:
        codes = load_codes()
    out = df.copy()
    if phone_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[phone_col].apply(lambda p: match_phone(p, codes))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [j for _, j in results]
    return out
