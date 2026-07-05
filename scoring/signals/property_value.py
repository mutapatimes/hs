"""Property-value signal (from open price data).

Flags customers whose billing/shipping postcode maps to a high median property value,
defined by an editable reference table (see reference_data/postcodes/uk_property_values.csv).
Property value is a WEALTH FACT, so this signal is ON by default; it is not an origin proxy.

Matching is EXACT FULL POSTCODE first, then district as a fallback. A full UK postcode
covers only ~15 homes (often one building or street segment), so its median sale price is a
tight proxy for the actual house at that address, e.g. "SW1A 1AA". If the table has no exact
row for that postcode, the signal falls back to the OUTCODE / district median (e.g. "SW1A").
Exact matching is what catches a genuinely valuable address on an ordinary-looking street,
where the whole-district median would be dragged below the threshold.

Both the billing and the shipping postcode are scanned; the higher-value match wins.

Each listed row carries a tier (ultra / prime / high) that grades how strong the tell is;
the combiner maps the tier to a weight (see PROPERTY_TIER_WEIGHTS). The seed table is curated
at district level; regenerate it to full national, full-postcode coverage from HM Land Registry
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


def match_postcode(postcode: object, table: dict[str, dict]) -> tuple[bool, str | None, str | None]:
    """Return (is_high_value, tier, reason) for one postcode.

    Exact full-postcode match first (the actual house), then the district/outcode fallback."""
    compact = _compact(postcode)
    if compact is None:
        return False, None, None
    # 1) exact full postcode — the tightest, actual-address match.
    if len(compact) >= 5:
        entry = table.get(compact)
        if entry is not None:
            area = entry["area"]
            pretty = _pretty(compact)
            reason = f"{area} ({pretty})" if area else pretty
            return True, entry["tier"], reason
    # 2) district / outcode fallback.
    outcode = compact[:-_INWARD_LEN] if len(compact) >= 5 else compact
    entry = table.get(outcode)
    if entry is not None:
        reason = f"{entry['area']} ({outcode})"
        return True, entry["tier"], reason
    return False, None, None


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
