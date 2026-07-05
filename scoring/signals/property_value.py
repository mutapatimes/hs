"""Property-value signal (from open price data).

Flags customers whose billing/shipping postcode maps to a high median property value,
defined by an editable reference table (see reference_data/postcodes/uk_property_values.csv).
Property value is a WEALTH FACT, so this signal is ON by default; it is not an origin proxy.

This module exposes TWO separate signals, because "this exact house is worth £X" and "this is
an expensive area" are different strengths of evidence:

  - property_value  -> EXACT full postcode, the actual house (e.g. "SW1A 1AA"). A full UK
    postcode is ~15 homes (often one building or street segment), so its median sale price is a
    tight proxy for that specific address. Weight scales CONTINUOUSLY with the median price
    (a £50M home outweighs a £2M one). This is the strong, precise tell.
  - property_area   -> the OUTCODE / district (e.g. "SW1A"), a high-net-worth area. Coarser and
    weaker; graded by tier, not price. This is the broad-coverage tell.

Both scan the billing AND shipping postcode; the higher-value match wins. Neither surfaces the
raw £ price to the merchant, only a value GRADE (Ultra-prime / Prime / High-value), since showing
an estimated home price reads as intrusive.

The seed table is curated at district level (so property_area works out of the box; property_value
starts firing once you add full-postcode rows). Regenerate to full national, full-postcode
coverage from HM Land Registry Price Paid Data with scripts/build_property_values.py.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import UK_PROPERTY_VALUES_FILE
from scoring.signals.hnwi_postcode import PLACEHOLDER_POSTCODES

# Two distinct signals share this table:
#   property_value  -> EXACT full postcode: the actual house. Weight scales with its median price.
#   property_area   -> the OUTCODE / district: a high-net-worth area. Weight is a coarse grade.
FLAG_COL = "property_value"
TIER_COL = "property_value_tier"
REASON_COL = "property_value_reason"
PRICE_COL = "property_value_price"   # the matched median price; combiner scales weight by it (never shown)

AREA_FLAG_COL = "property_area"
AREA_TIER_COL = "property_area_tier"
AREA_REASON_COL = "property_area_reason"

# UK inward code (the part after the space) is always 3 chars: digit + 2 letters.
_INWARD_LEN = 3
_VALID_TIERS = {"ultra", "prime", "high"}

# A value GRADE surfaced to the merchant instead of the raw £ price (showing an estimated
# property price for someone's home reads as intrusive; the grade conveys the tell honestly).
GRADE_WORD = {"ultra": "Ultra-prime", "prime": "Prime", "high": "High-value"}


def _normalize(value: object) -> str | None:
    """Upper-case, trim, and collapse internal whitespace. None for blanks."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value).strip().upper())
    return text or None


def _compact(postcode: object) -> str | None:
    """Spaceless, upper-cased postcode, e.g. 'sw1a 1aa' -> 'SW1A1AA'. None for blanks."""
    norm = _normalize(postcode)
    if norm is None or norm in PLACEHOLDER_POSTCODES:
        return None
    compact = norm.replace(" ", "")
    return compact if len(compact) >= 2 else None


def _outcode(postcode: object) -> str | None:
    """The district (outward code) of a UK postcode, e.g. 'SW10 9SJ' -> 'SW10'."""
    compact = _compact(postcode)
    if compact is None:
        return None
    # A full postcode ends with a 3-char inward code; a bare outcode is already the district.
    return compact[:-_INWARD_LEN] if len(compact) >= 5 else compact


def _pretty(compact: str) -> str:
    """Re-insert the space in a full postcode for display: 'SW1A1AA' -> 'SW1A 1AA'."""
    return f"{compact[:-_INWARD_LEN]} {compact[-_INWARD_LEN:]}" if len(compact) >= 5 else compact


# NOTE: the signal still grades by the area's median sale price internally (it sets the
# ultra/prime/high TIER that drives the weight), but we deliberately DO NOT surface a money
# figure in the reason — showing a merchant an estimated property value for their customer reads
# as intrusive/surveillance. The reason is the area name only, like the other geography tells.


def load_values(path: Path | str = UK_PROPERTY_VALUES_FILE) -> dict[str, dict]:
    """Read the reference table: {KEY: {tier, price, area}}.

    A KEY is a spaceless upper-cased postcode: either a FULL postcode ("SW1A1AA", used for
    exact matching) or an OUTCODE ("SW1A", used for the district fallback). Skips comment
    lines (starting with '#'), the header, and any row whose tier is not ultra/prime/high.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Property-value reference table not found: {path}")

    table: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip()
            if not first or first.startswith("#") or first.lower() in ("outcode", "postcode"):
                continue
            if len(row) < 4:
                continue
            key = first.replace(" ", "").upper()
            area = row[1].strip()
            try:
                price = int(float(row[2]))
            except (TypeError, ValueError):
                continue
            tier = row[3].strip().lower()
            if tier not in _VALID_TIERS:
                continue
            table[key] = {"tier": tier, "price": price, "area": area}
    return table


def _lookup_exact(postcode: object, table: dict[str, dict]) -> dict | None:
    """The EXACT full postcode (the actual house), or None. Reason is a value GRADE."""
    compact = _compact(postcode)
    if compact is None or len(compact) < 5:
        return None
    entry = table.get(compact)
    if entry is None:
        return None
    grade = GRADE_WORD.get(entry["tier"], entry["tier"].title())
    return {"tier": entry["tier"], "price": entry["price"],
            "reason": f"{grade} ({_pretty(compact)})"}


def _lookup_area(postcode: object, table: dict[str, dict]) -> dict | None:
    """The OUTCODE / district (a high-net-worth area), or None. Reason is a value GRADE."""
    compact = _compact(postcode)
    if compact is None:
        return None
    outcode = compact[:-_INWARD_LEN] if len(compact) >= 5 else compact
    entry = table.get(outcode)
    if entry is None:
        return None
    grade = GRADE_WORD.get(entry["tier"], entry["tier"].title())
    where = entry["area"] or outcode
    return {"tier": entry["tier"], "price": entry["price"], "reason": f"{grade} ({where})"}


def match_postcode(postcode: object, table: dict[str, dict]) -> tuple[bool, str | None, str | None]:
    """Return (is_high_value, tier, reason) for one postcode: exact house, else the area."""
    m = _lookup_exact(postcode, table) or _lookup_area(postcode, table)
    return (True, m["tier"], m["reason"]) if m else (False, None, None)


def _flag(df, table, lookup, flag_col, tier_col, reason_col, price_col, zip_cols):
    """Shared scanner: run ``lookup`` over billing+shipping; the higher-value match wins."""
    out = df.copy()
    cols = [c for c in (zip_cols or ["LATEST_BILLING_ZIP", "LATEST_SHIPPING_ZIP"])
            if c in out.columns]
    if not cols:
        out[flag_col] = False
        out[tier_col] = None
        out[reason_col] = None
        if price_col:
            out[price_col] = 0
        return out

    def _match(row):
        best = None
        for c in cols:
            m = lookup(row[c], table)
            if m and (best is None or m["price"] > best["price"]):
                best = m
        return best

    results = out.apply(_match, axis=1)
    out[flag_col] = [m is not None for m in results]
    out[tier_col] = [m["tier"] if m else None for m in results]
    out[reason_col] = [m["reason"] if m else None for m in results]
    if price_col:
        out[price_col] = [m["price"] if m else 0 for m in results]
    return out


def flag_property_value(df: pd.DataFrame, table: dict[str, dict] | None = None,
                        zip_cols: list[str] | None = None) -> pd.DataFrame:
    """EXACT full-postcode match (the actual house). Scans billing+shipping; higher value wins;
    weight scales with the matched median price."""
    if table is None:
        table = load_values()
    return _flag(df, table, _lookup_exact, FLAG_COL, TIER_COL, REASON_COL, PRICE_COL, zip_cols)


def flag_property_area(df: pd.DataFrame, table: dict[str, dict] | None = None,
                       zip_cols: list[str] | None = None) -> pd.DataFrame:
    """OUTCODE / district match (a high-net-worth area). Coarser than the exact house; graded
    by tier, not price."""
    if table is None:
        table = load_values()
    return _flag(df, table, _lookup_area, AREA_FLAG_COL, AREA_TIER_COL, AREA_REASON_COL, None, zip_cols)
