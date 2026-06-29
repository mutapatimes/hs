"""US ultra-prime ZIP-code signal.

Flags customers whose US billing ZIP falls in an ultra-high-net-worth area
(reference_data/postcodes/us_hnwi_zips.csv). US ZIPs are 5 digits, so this is a
separate signal from the UK postcode matcher. ZIP+4 (e.g. 90210-1234) is reduced
to its 5-digit prefix before matching. UK postcodes (which always contain
letters) never produce 5 digits, so they can't false-fire here.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import US_HNWI_ZIPS_FILE

FLAG_COL = "us_hnwi_zip"
REASON_COL = "us_hnwi_zip_reason"


def _zip5(value: object) -> str | None:
    """Return the 5-digit ZIP prefix, or None if there aren't 5 digits."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits[:5] if len(digits) >= 5 else None


def load_zips(path: Path | str = US_HNWI_ZIPS_FILE) -> dict[str, str]:
    """Read the reference list -> {zip5: area_label}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"US HNWI ZIP reference list not found: {path}")
    zips: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            cell = row[0].strip()
            if not cell or cell.startswith("#") or cell.lower() == "zip":
                continue
            z = _zip5(cell)
            if z:
                area = row[1].strip() if len(row) > 1 else ""
                zips[z] = area or z
    return zips


def match_zip(value: object, zips: dict[str, str]) -> tuple[bool, str | None]:
    """Return (is_hnwi, reason) for one billing ZIP."""
    z = _zip5(value)
    if z is None or z not in zips:
        return False, None
    area = zips[z]
    return True, f"{area} ({z})" if area and area != z else z


def flag_us_zip(
    df: pd.DataFrame,
    zips: dict[str, str] | None = None,
    zip_col: str = "LATEST_BILLING_ZIP",
    zip_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Add US prime-ZIP flag + reason columns. Scans billing then shipping ZIP."""
    if zips is None:
        zips = load_zips()
    out = df.copy()
    cols = [c for c in (zip_cols or [zip_col, "LATEST_SHIPPING_ZIP"]) if c in out.columns]
    if not cols:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    def _match(row):
        for c in cols:
            hit, reason = match_zip(row[c], zips)
            if hit:
                return hit, reason
        return False, None

    results = out.apply(_match, axis=1)
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
