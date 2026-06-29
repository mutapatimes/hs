"""International HNW postcode signal (country-guarded).

Flags customers whose BILLING or SHIPPING postcode is an ultra-prime area in
France, Italy, Switzerland, Luxembourg, Germany, China, Japan, Monaco, and GCC
states with usable postcodes (reference_data/postcodes/intl_hnwi_postcodes.csv).

Postal formats differ by country and digit-prefixes COLLIDE across countries
(Tokyo 100-xxxx vs Beijing 100xxx), so every match is GUARDED by the country:
the billing ZIP is only matched against billing-country prefixes, and likewise
for shipping. ZIPs are reduced to digits-only before prefix matching, so
"L-1009", "106-0032" and "8001" all normalise cleanly. UK/US ZIPs are handled
by their own signals.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import INTL_HNWI_POSTCODES_FILE

FLAG_COL = "intl_postcode"
REASON_COL = "intl_postcode_reason"


def _norm_country(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[^A-Z0-9]+", " ", str(value).upper()).strip()


def _digits(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\D", "", str(value))


def load_postcodes(
    path: Path | str = INTL_HNWI_POSTCODES_FILE,
) -> list[tuple[str, str, str, str]]:
    """Read [(country_norm, digit_prefix, country_label, area)], longest prefix first."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Intl HNWI postcode reference not found: {path}")
    rows: list[tuple[str, str, str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            country = row[0].strip()
            if not country or country.startswith("#") or country.lower() == "country":
                continue
            prefix = _digits(row[1]) if len(row) > 1 else ""
            area = row[2].strip() if len(row) > 2 else ""
            if prefix:
                rows.append((_norm_country(country), prefix, country, area))
    return sorted(rows, key=lambda r: -len(r[1]))


def match_postcode(
    zip_value: object, country_value: object, rows: list[tuple[str, str, str, str]]
) -> tuple[bool, str | None]:
    """Match a ZIP only against prefixes whose country matches this address."""
    digits = _digits(zip_value)
    country = _norm_country(country_value)
    if not digits or not country:
        return False, None
    for country_norm, prefix, label, area in rows:
        if country_norm in country and digits.startswith(prefix):
            place = area or label
            return True, f"{place} ({label})" if area else label
    return False, None


def flag_intl_postcode(
    df: pd.DataFrame,
    rows: list[tuple[str, str, str, str]] | None = None,
    sides: list[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """Add intl-postcode flag + reason. ``sides`` = [(zip_col, country_col), ...]."""
    if rows is None:
        rows = load_postcodes()
    if sides is None:
        sides = [
            ("LATEST_BILLING_ZIP", "LATEST_BILLING_ADDRESS4"),
            ("LATEST_SHIPPING_ZIP", "LATEST_SHIPPING_ADDRESS4"),
        ]
    sides = [(z, c) for z, c in sides if z in df.columns and c in df.columns]

    out = df.copy()
    if not sides:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    def _match(row):
        for zip_col, country_col in sides:
            hit, reason = match_postcode(row[zip_col], row[country_col], rows)
            if hit:
                return hit, reason
        return False, None

    results = out.apply(_match, axis=1)
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
