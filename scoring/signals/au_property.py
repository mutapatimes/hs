"""Australia high-value home-area signal (from NSW Valuer General open sales data).

Flags customers whose Australian billing/shipping postcode maps to a high median residential
sale price, from an editable reference table (reference_data/postcodes/au_property_values.csv,
rebuilt from the NSW Valuer General's bulk property sales with scripts/build_au_property.py;
other states' registers are commercial, so their prime postcodes stay curated). Home value is
a WEALTH FACT, so this is on by default; it is not an origin proxy.

Same shape as ``fr_property``: an AREA signal graded by TIER, never by the raw A$ figure.
An Australian postcode is four digits, exactly like Norway's, Denmark's, Switzerland's and
more (2027 is Point Piper AND a Norwegian rural code), so this signal is COUNTRY-GATED — a
postcode only matches when its OWN address's country column says Australia. A row with no
country on file never fires here, rather than guessing.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

from config import AU_PROPERTY_VALUES_FILE

FLAG_COL = "au_property"
TIER_COL = "au_property_tier"
REASON_COL = "au_property_reason"

_VALID_TIERS = {"ultra", "prime", "high"}
_TIER_RANK = {"high": 1, "prime": 2, "ultra": 3}
GRADE_WORD = {"ultra": "Ultra-prime", "prime": "Prime", "high": "High-value"}

# Each postcode column is gated by ITS OWN address's country column.
_COL_PAIRS = [("LATEST_BILLING_ZIP", "LATEST_BILLING_ADDRESS4"),
              ("LATEST_SHIPPING_ZIP", "LATEST_SHIPPING_ADDRESS4")]
_AUSTRALIA = {"australia", "au", "aus", "commonwealth of australia"}


def _is_australia(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", " ", folded).strip() in _AUSTRALIA


def _pc4(value: object) -> str | None:
    """An Australian postcode: exactly four digits (leading zeros matter: 0870 Alice Springs)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits if len(digits) == 4 else None


def load_values(path: Path | str = AU_PROPERTY_VALUES_FILE) -> dict[str, dict]:
    """Read the reference table: {postcode: {tier, area}} from postcode,area,value,tier rows."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Australia property-value reference table not found: {path}")
    table: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip()
            if not first or first.startswith("#") or first.lower() in ("postcode", "post_code"):
                continue
            if len(row) < 4:
                continue
            pc = _pc4(first)
            tier = row[3].strip().lower()
            if pc and tier in _VALID_TIERS:
                table[pc] = {"tier": tier, "area": row[1].strip()}
    return table


def match_pc(value: object, country: object, table: dict[str, dict]) -> tuple[bool, str | None, str | None]:
    """(is_high_value, tier, reason) for one postcode+country. Reason is a GRADE, not a price."""
    if not _is_australia(country):
        return False, None, None
    pc = _pc4(value)
    if pc is None or pc not in table:
        return False, None, None
    entry = table[pc]
    grade = GRADE_WORD.get(entry["tier"], entry["tier"].title())
    where = entry["area"] or pc
    return True, entry["tier"], f"{grade} ({where})"


def flag_au_property(df: pd.DataFrame, table: dict[str, dict] | None = None) -> pd.DataFrame:
    """Add the Australia home-value flag/tier/reason columns. Billing then shipping; higher tier wins."""
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
