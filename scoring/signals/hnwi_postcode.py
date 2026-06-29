"""HNWI postcode signal.

Flags customers whose billing postcode falls inside an ultra-prime ("high
net worth") area, defined by an editable reference list of postcode prefixes
(see reference_data/postcodes/hnwi_postcodes.csv).

Matching is prefix-based and granularity-aware, so a reference entry can be:
    - a full unit     "SW10 9SJ"  -> only that exact postcode
    - a sector        "SW10 9"    -> any postcode in that sector
    - a district      "SW10"      -> any postcode in that district
District boundaries are respected: prefix "SW1" never matches "SW10 9SJ".
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import HNWI_POSTCODES_FILE

FLAG_COL = "hnwi_postcode"
REASON_COL = "hnwi_postcode_reason"

# UK inward code (the part after the space) is always 3 chars: digit + 2 letters.
_INWARD_LEN = 3

# Westminster government addresses that real customers never live at — these are the
# canonical UK placeholder/default postcodes (e.g. PayPal guest checkouts with no
# postcode shared, or test data). Ignore them so they don't false-fire as ultra-prime.
PLACEHOLDER_POSTCODES = {
    "SW1A 0AA",  # Palace of Westminster / House of Commons
    "SW1A 0PW",  # House of Lords
    "SW1A 1AA",  # Buckingham Palace (the classic UK test postcode)
    "SW1A 2AA",  # 10 Downing Street / Cabinet Office
    "SW1A 2AB",  # Downing Street
    "EC4N 8AF",  # Bank of England (occasional default)
}


def _normalize(value: object) -> str | None:
    """Upper-case, trim, and collapse internal whitespace. None for blanks."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value).strip().upper())
    return text or None


def _split_full(postcode: str) -> tuple[str, str]:
    """Split a full customer postcode into (outward, inward) parts."""
    compact = postcode.replace(" ", "")
    return compact[:-_INWARD_LEN], compact[-_INWARD_LEN:]


def _split_prefix(prefix: str) -> tuple[str, str]:
    """Split a reference prefix into (outward, inward-fragment).

    A space separates the district from a sector/unit fragment. With no space
    the prefix is a whole district and the inward fragment is empty.
    """
    outward, _, inward = prefix.partition(" ")
    return outward, inward


def load_prefixes(path: Path | str = HNWI_POSTCODES_FILE) -> list[str]:
    """Read the reference list, returning normalized prefixes.

    Skips comment lines (starting with '#') and blank entries.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"HNWI postcode reference list not found: {path}")

    prefixes: list[str] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            cell = row[0].strip()
            if not cell or cell.startswith("#") or cell.lower() == "prefix":
                continue
            norm = _normalize(cell)
            if norm:
                prefixes.append(norm)
    return prefixes


def match_postcode(
    postcode: object, prefixes: list[str]
) -> tuple[bool, str | None]:
    """Return (is_hnwi, matched_prefix). Reason is the prefix that matched."""
    norm = _normalize(postcode)
    if norm is None or norm in PLACEHOLDER_POSTCODES:
        return False, None

    cust_out, cust_in = _split_full(norm)
    for prefix in prefixes:
        pre_out, pre_in = _split_prefix(prefix)
        if cust_out != pre_out:
            continue
        if pre_in == "" or cust_in.startswith(pre_in):
            return True, prefix
    return False, None


def flag_hnwi_postcode(
    df: pd.DataFrame,
    prefixes: list[str] | None = None,
    zip_col: str = "LATEST_BILLING_ZIP",
    zip_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Add HNWI postcode flag + reason columns to a copy of ``df``.

    Scans BOTH the billing and shipping ZIP by default (first match wins).
    """
    if prefixes is None:
        prefixes = load_prefixes()
    out = df.copy()
    cols = [c for c in (zip_cols or [zip_col, "LATEST_SHIPPING_ZIP"]) if c in out.columns]
    if not cols:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    def _match(row):
        for c in cols:
            hit, reason = match_postcode(row[c], prefixes)
            if hit:
                return hit, reason
        return False, None

    results = out.apply(_match, axis=1)
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
