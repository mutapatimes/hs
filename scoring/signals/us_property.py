"""US high-value home-area signal (from open home-value data).

Flags customers whose US billing/shipping ZIP maps to a high median home value, from an editable
reference table (reference_data/postcodes/us_property_values.csv, built from Zillow's ZHVI ZIP-code
data with scripts/build_us_property.py). Home value is a WEALTH FACT, so this is on by default; it
is not an origin proxy.

The US analog to the UK ``property_area`` signal. Graded by TIER (Ultra-prime / Prime), never by
the raw $ value — showing an estimated home price for someone's address reads as intrusive. Scans
the billing then shipping ZIP; the higher tier wins. ZIP+4 is reduced to its 5-digit prefix.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import US_PROPERTY_VALUES_FILE

FLAG_COL = "us_property"
TIER_COL = "us_property_tier"
REASON_COL = "us_property_reason"

_VALID_TIERS = {"ultra", "prime"}
_TIER_RANK = {"prime": 1, "ultra": 2}
# A value GRADE surfaced to the merchant instead of the raw $ price (an estimated home value reads
# as surveillance; the grade conveys the tell honestly, like the other geography signals).
GRADE_WORD = {"ultra": "Ultra-prime", "prime": "Prime"}


def _zip5(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits[:5] if len(digits) >= 5 else None


def load_values(path: Path | str = US_PROPERTY_VALUES_FILE) -> dict[str, dict]:
    """Read the reference table: {zip5: {tier, area}} from zip,area,value,tier rows."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"US property-value reference table not found: {path}")
    table: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip()
            if not first or first.startswith("#") or first.lower() in ("zip", "zipcode"):
                continue
            if len(row) < 4:
                continue
            z = _zip5(first)
            tier = row[3].strip().lower()
            if z and tier in _VALID_TIERS:
                table[z] = {"tier": tier, "area": row[1].strip()}
    return table


def match_zip(value: object, table: dict[str, dict]) -> tuple[bool, str | None, str | None]:
    """Return (is_high_value, tier, reason) for one ZIP. Reason is a value GRADE, not a price."""
    z = _zip5(value)
    if z is None or z not in table:
        return False, None, None
    entry = table[z]
    grade = GRADE_WORD.get(entry["tier"], entry["tier"].title())
    where = entry["area"] or z
    return True, entry["tier"], f"{grade} ({where})"


def flag_us_property(
    df: pd.DataFrame,
    table: dict[str, dict] | None = None,
    zip_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Add the US home-value flag/tier/reason columns. Scans billing then shipping ZIP; higher tier wins."""
    if table is None:
        table = load_values()
    out = df.copy()
    cols = [c for c in (zip_cols or ["LATEST_BILLING_ZIP", "LATEST_SHIPPING_ZIP"]) if c in out.columns]
    if not cols:
        out[FLAG_COL] = False
        out[TIER_COL] = None
        out[REASON_COL] = None
        return out

    def _best(row):
        best = (False, None, None)
        for c in cols:
            hit, tier, reason = match_zip(row[c], table)
            if hit and _TIER_RANK.get(tier, 0) > _TIER_RANK.get(best[1], 0):
                best = (hit, tier, reason)
        return best

    res = out.apply(_best, axis=1)
    out[FLAG_COL] = [h for h, _, _ in res]
    out[TIER_COL] = [t for _, t, _ in res]
    out[REASON_COL] = [r for _, _, r in res]
    return out
