"""UAE high-value community signal (from Dubai Land Department open data).

Flags customers whose UAE billing/shipping address names a high-value residential community,
from an editable reference table (reference_data/locations/ae_property_values.csv, rebuilt from
the DLD's open transaction data with scripts/build_ae_property.py). Home value is a WEALTH
FACT, so this is on by default; it is not an origin proxy.

The UAE has no postcodes, so unlike the UK/US/France property signals this one matches
COMMUNITY NAMES inside the address text ("Villa 12, Emirates Hills, Dubai"), whole-word and
accent-insensitive, the same approach as the hnw_area signal. It is COUNTRY-GATED: a name
only counts when the address's own country column says the United Arab Emirates, so a
"Marina" in Marseille never fires. Graded by TIER, never by the raw AED figure.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

from config import AE_PROPERTY_VALUES_FILE

FLAG_COL = "ae_property"
TIER_COL = "ae_property_tier"
REASON_COL = "ae_property_reason"

_VALID_TIERS = {"ultra", "prime", "high"}
_TIER_RANK = {"high": 1, "prime": 2, "ultra": 3}
GRADE_WORD = {"ultra": "Ultra-prime", "prime": "Prime", "high": "High-value"}

# Address text is scanned per side; each side is gated by its own country column.
_SIDES = [(["LATEST_BILLING_ADDRESS1", "LATEST_BILLING_ADDRESS2", "LATEST_BILLING_ADDRESS3"],
           "LATEST_BILLING_ADDRESS4"),
          (["LATEST_SHIPPING_ADDRESS1", "LATEST_SHIPPING_ADDRESS2", "LATEST_SHIPPING_ADDRESS3"],
           "LATEST_SHIPPING_ADDRESS4")]
_UAE = {"united arab emirates", "uae", "u a e", "are", "ae", "dubai", "abu dhabi"}


def _fold(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def _is_uae(value: object) -> bool:
    return _fold(value) in _UAE


def load_values(path: Path | str = AE_PROPERTY_VALUES_FILE) -> list[dict]:
    """Read the table: [{name, needle, tier, emirate}], longest needle first so 'Palm Jumeirah'
    wins over any shorter name it contains."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"UAE property-value reference table not found: {path}")
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or not row[0].strip() or row[0].startswith("#") or row[0].lower() == "area":
                continue
            if len(row) < 4:
                continue
            name, emirate, tier = row[0].strip(), row[1].strip(), row[3].strip().lower()
            needle = _fold(name)
            if needle and tier in _VALID_TIERS:
                rows.append({"name": name, "needle": needle, "tier": tier, "emirate": emirate})
    rows.sort(key=lambda r: len(r["needle"]), reverse=True)
    return rows


def match_address(text: object, country: object, table: list[dict]) -> tuple[bool, str | None, str | None]:
    """(is_high_value, tier, reason) for one address side. Reason is a GRADE, not a price."""
    if not _is_uae(country):
        return False, None, None
    haystack = f" {_fold(text)} "
    if not haystack.strip():
        return False, None, None
    for row in table:
        if f" {row['needle']} " in haystack:
            grade = GRADE_WORD.get(row["tier"], row["tier"].title())
            return True, row["tier"], f"{grade} ({row['name']})"
    return False, None, None


def flag_ae_property(df: pd.DataFrame, table: list[dict] | None = None) -> pd.DataFrame:
    """Add the UAE community flag/tier/reason columns. Billing then shipping; higher tier wins."""
    if table is None:
        table = load_values()
    out = df.copy()
    sides = [([c for c in cols if c in out.columns], ccol)
             for cols, ccol in _SIDES]
    sides = [(cols, ccol) for cols, ccol in sides if cols]
    if not sides:
        out[FLAG_COL] = False
        out[TIER_COL] = None
        out[REASON_COL] = None
        return out

    def _best(row):
        best = (False, None, None)
        for cols, ccol in sides:
            country = row[ccol] if ccol in row.index else None
            text = " ".join(str(row[c]) for c in cols if not pd.isna(row[c]))
            hit, tier, reason = match_address(text, country, table)
            if hit and _TIER_RANK.get(tier, 0) > _TIER_RANK.get(best[1], 0):
                best = (hit, tier, reason)
        return best

    res = out.apply(_best, axis=1)
    out[FLAG_COL] = [h for h, _, _ in res]
    out[TIER_COL] = [t for _, t, _ in res]
    out[REASON_COL] = [r for _, _, r in res]
    return out
