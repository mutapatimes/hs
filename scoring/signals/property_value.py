"""Property-value signal (area-level, from open price data).

Flags customers whose billing/shipping postcode falls in an area with a high
median property value, defined by an editable reference table keyed on postcode
OUTCODE (see reference_data/postcodes/uk_property_values.csv). Property value is a
WEALTH FACT, so this signal is ON by default; it is not an origin proxy.

Each listed outcode carries a tier (ultra / prime / high) that grades how strong the
tell is; the combiner maps the tier to a weight (see PROPERTY_TIER_WEIGHTS). Matching
is at outcode (district) granularity: the part of the postcode before the inward code,
e.g. "SW10 9SJ" -> "SW10". This catches the genuinely valuable address on an ordinary
looking street that a hand-picked ultra-prime list would miss, and grades by real local
value rather than mere membership of a famous district.

The seed table is curated; regenerate it to full national coverage from HM Land Registry
Price Paid Data with scripts/build_property_values.py.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import UK_PROPERTY_VALUES_FILE
from scoring.signals.hnwi_postcode import PLACEHOLDER_POSTCODES

FLAG_COL = "property_value"
TIER_COL = "property_value_tier"
REASON_COL = "property_value_reason"

# UK inward code (the part after the space) is always 3 chars: digit + 2 letters.
_INWARD_LEN = 3
_VALID_TIERS = {"ultra", "prime", "high"}


def _normalize(value: object) -> str | None:
    """Upper-case, trim, and collapse internal whitespace. None for blanks."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value).strip().upper())
    return text or None


def _outcode(postcode: object) -> str | None:
    """The district (outward code) of a UK postcode, e.g. 'SW10 9SJ' -> 'SW10'.

    Returns None for blanks, placeholders, and anything too short to be a real postcode.
    """
    norm = _normalize(postcode)
    if norm is None or norm in PLACEHOLDER_POSTCODES:
        return None
    compact = norm.replace(" ", "")
    if len(compact) <= _INWARD_LEN:
        return None
    return compact[:-_INWARD_LEN]


def _human_price(price: int) -> str:
    """1300000 -> '£1.3m'; 760000 -> '£760k'."""
    if price >= 1_000_000:
        return f"£{price / 1_000_000:.1f}m".replace(".0m", "m")
    return f"£{round(price / 1000)}k"


def load_values(path: Path | str = UK_PROPERTY_VALUES_FILE) -> dict[str, dict]:
    """Read the reference table: {OUTCODE: {tier, price, area}}.

    Skips comment lines (starting with '#'), the header, and any row whose tier is
    not one of ultra/prime/high.
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
            if not first or first.startswith("#") or first.lower() == "outcode":
                continue
            if len(row) < 4:
                continue
            outcode = first.replace(" ", "").upper()
            area = row[1].strip()
            try:
                price = int(float(row[2]))
            except (TypeError, ValueError):
                continue
            tier = row[3].strip().lower()
            if tier not in _VALID_TIERS:
                continue
            table[outcode] = {"tier": tier, "price": price, "area": area}
    return table


def match_postcode(postcode: object, table: dict[str, dict]) -> tuple[bool, str | None, str | None]:
    """Return (is_high_value, tier, reason) for one postcode."""
    outcode = _outcode(postcode)
    if outcode is None:
        return False, None, None
    entry = table.get(outcode)
    if entry is None:
        return False, None, None
    reason = f"{entry['area']} ({outcode}), approx {_human_price(entry['price'])}"
    return True, entry["tier"], reason


def flag_property_value(
    df: pd.DataFrame,
    table: dict[str, dict] | None = None,
    zip_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Add property_value flag + tier + reason columns to a copy of ``df``.

    Scans BOTH the billing and shipping ZIP by default (the higher-value area wins, so
    a customer is graded by their best address).
    """
    if table is None:
        table = load_values()
    out = df.copy()
    cols = [c for c in (zip_cols or ["LATEST_BILLING_ZIP", "LATEST_SHIPPING_ZIP"])
            if c in out.columns]
    if not cols:
        out[FLAG_COL] = False
        out[TIER_COL] = None
        out[REASON_COL] = None
        return out

    _rank = {"ultra": 3, "prime": 2, "high": 1}

    def _match(row):
        best = (False, None, None)
        best_rank = 0
        for c in cols:
            hit, tier, reason = match_postcode(row[c], table)
            if hit and _rank.get(tier, 0) > best_rank:
                best, best_rank = (hit, tier, reason), _rank.get(tier, 0)
        return best

    results = out.apply(_match, axis=1)
    out[FLAG_COL] = [hit for hit, _, _ in results]
    out[TIER_COL] = [tier for _, tier, _ in results]
    out[REASON_COL] = [reason for _, _, reason in results]
    return out
