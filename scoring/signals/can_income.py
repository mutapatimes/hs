"""Canada high-income area signal (from CRA open taxation statistics).

Flags customers whose Canadian postal code sits in a high average-income FORWARD SORTATION
AREA (the first three characters, letter-digit-letter), from an editable reference table
(reference_data/postcodes/can_income_values.csv, rebuilt from the Canada Revenue Agency's
annual FSA tax statistics with scripts/build_can_income.py). Area income is a WEALTH FACT,
so this is on by default; it is not an origin proxy.

Canada has no open transaction register (provincial assessment rolls are commercial), so the
CRA table IS the national wealth-geography source: Rosedale, Westmount, West Vancouver and
their peers all surface directly from taxfiler averages. COUNTRY-GATED like the other
postcode signals - a UK outcode such as W1A shares the letter-digit-letter shape, so a match
only counts when the address's own country column says Canada. Graded by TIER, never by the
raw dollar figure.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

from config import CAN_INCOME_VALUES_FILE

FLAG_COL = "can_income"
TIER_COL = "can_income_tier"
REASON_COL = "can_income_reason"

_VALID_TIERS = {"ultra", "prime", "high"}
_TIER_RANK = {"high": 1, "prime": 2, "ultra": 3}
GRADE_WORD = {"ultra": "Top-income area", "prime": "High-income area", "high": "Affluent area"}

# Each postal-code column is gated by ITS OWN address's country column.
_COL_PAIRS = [("LATEST_BILLING_ZIP", "LATEST_BILLING_ADDRESS4"),
              ("LATEST_SHIPPING_ZIP", "LATEST_SHIPPING_ADDRESS4")]
_CANADA = {"canada", "ca", "can"}

_FSA_RE = re.compile(r"^[A-Z][0-9][A-Z]")


def _is_canada(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", " ", folded).strip() in _CANADA


def _fsa(value: object) -> str | None:
    """The FSA of a Canadian postal code: 'M4W 1A5' / 'm4w1a5' / 'M4W' -> 'M4W'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()
    m = _FSA_RE.match(cleaned)
    return m.group(0) if m and len(cleaned) in (3, 6) else None


def load_values(path: Path | str = CAN_INCOME_VALUES_FILE) -> dict[str, dict]:
    """Read the reference table: {fsa: {tier, area}} from fsa,area,value,tier rows."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Canada income reference table not found: {path}")
    table: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip().upper()
            if not first or first.startswith("#") or first == "FSA":
                continue
            if len(row) < 4:
                continue
            tier = row[3].strip().lower()
            if _FSA_RE.fullmatch(first) and tier in _VALID_TIERS:
                table[first] = {"tier": tier, "area": row[1].strip()}
    return table


def match_pc(value: object, country: object, table: dict[str, dict]) -> tuple[bool, str | None, str | None]:
    """(is_high_income, tier, reason) for one postal code+country. Reason is a GRADE, not a figure."""
    if not _is_canada(country):
        return False, None, None
    fsa = _fsa(value)
    if fsa is None or fsa not in table:
        return False, None, None
    entry = table[fsa]
    grade = GRADE_WORD.get(entry["tier"], entry["tier"].title())
    where = entry["area"] or fsa
    return True, entry["tier"], f"{grade} ({where})"


def flag_can_income(df: pd.DataFrame, table: dict[str, dict] | None = None) -> pd.DataFrame:
    """Add the Canada income flag/tier/reason columns. Billing then shipping; higher tier wins."""
    if table is None:
        table = load_values()
    out = df.copy()
    pairs = [(z, c) for z, c in _COL_PAIRS if z in out.columns]
    if not pairs:
        out[FLAG_COL] = False
        out[TIER_COL] = None
        out[REASON_COL] = None
        return out

    def _best(row):
        best = (False, None, None)
        for zcol, ccol in pairs:
            country = row[ccol] if ccol in row.index else None
            hit, tier, reason = match_pc(row[zcol], country, table)
            if hit and _TIER_RANK.get(tier, 0) > _TIER_RANK.get(best[1], 0):
                best = (hit, tier, reason)
        return best

    res = out.apply(_best, axis=1)
    out[FLAG_COL] = [h for h, _, _ in res]
    out[TIER_COL] = [t for _, t, _ in res]
    out[REASON_COL] = [r for _, _, r in res]
    return out
