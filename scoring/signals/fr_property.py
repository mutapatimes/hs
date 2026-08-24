"""France high-value home-area signal (from open DVF price data).

Flags customers whose French billing/shipping code postal maps to a high median sale price
per m², from an editable reference table (reference_data/postcodes/fr_property_values.csv,
built from the state's open DVF transaction data with scripts/build_fr_property.py). Home
value is a WEALTH FACT, so this is on by default; it is not an origin proxy.

The French analog to ``us_property``: an AREA signal graded by TIER (Ultra-prime / Prime /
High-value), never by the raw € figure. One structural difference matters: a French code
postal is five digits, exactly like a US ZIP (75001 is central Paris AND Addison, Texas), so
this signal is COUNTRY-GATED — a postcode only matches when its OWN address's country column
says France. A row with no country on file never fires here, rather than guessing.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

from config import FR_PROPERTY_VALUES_FILE

FLAG_COL = "fr_property"
TIER_COL = "fr_property_tier"
REASON_COL = "fr_property_reason"

_VALID_TIERS = {"ultra", "prime", "high"}
_TIER_RANK = {"high": 1, "prime": 2, "ultra": 3}
GRADE_WORD = {"ultra": "Ultra-prime", "prime": "Prime", "high": "High-value"}

# Each postcode column is gated by ITS OWN address's country column.
_COL_PAIRS = [("LATEST_BILLING_ZIP", "LATEST_BILLING_ADDRESS4"),
              ("LATEST_SHIPPING_ZIP", "LATEST_SHIPPING_ADDRESS4")]
_FRANCE = {"france", "fr", "fra", "french republic"}


def _is_france(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", " ", folded).strip() in _FRANCE


def _cp5(value: object) -> str | None:
    """A French code postal: exactly five digits (leading zeros matter: 06400 Cannes)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) == 5 else None


def load_values(path: Path | str = FR_PROPERTY_VALUES_FILE) -> dict[str, dict]:
    """Read the reference table: {code_postal: {tier, area}} from code,area,value,tier rows."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"France property-value reference table not found: {path}")
    table: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip()
            if not first or first.startswith("#") or first.lower() in ("code_postal", "postcode"):
                continue
            if len(row) < 4:
                continue
            cp = _cp5(first)
            tier = row[3].strip().lower()
            if cp and tier in _VALID_TIERS:
                table[cp] = {"tier": tier, "area": row[1].strip()}
    return table


def match_cp(value: object, country: object, table: dict[str, dict]) -> tuple[bool, str | None, str | None]:
    """(is_high_value, tier, reason) for one postcode+country. Reason is a GRADE, not a price."""
    if not _is_france(country):
        return False, None, None
    cp = _cp5(value)
    if cp is None or cp not in table:
        return False, None, None
    entry = table[cp]
    grade = GRADE_WORD.get(entry["tier"], entry["tier"].title())
    where = entry["area"] or cp
    return True, entry["tier"], f"{grade} ({where})"


def flag_fr_property(df: pd.DataFrame, table: dict[str, dict] | None = None) -> pd.DataFrame:
    """Add the France home-value flag/tier/reason columns. Billing then shipping; higher tier wins."""
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
            hit, tier, reason = match_cp(row[zcol], country, table)
            if hit and _TIER_RANK.get(tier, 0) > _TIER_RANK.get(best[1], 0):
                best = (hit, tier, reason)
        return best

    res = out.apply(_best, axis=1)
    out[FLAG_COL] = [h for h, _, _ in res]
    out[TIER_COL] = [t for _, t, _ in res]
    out[REASON_COL] = [r for _, _, r in res]
    return out
