"""GCC billing-country signal.

Flags customers whose registered billing country is a Gulf Cooperation Council
member state (Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman), defined by an
editable reference list (reference_data/countries/gcc_countries.csv).

Matching is case/punctuation-insensitive and accepts common variants ("UAE",
"KSA", "Kingdom of Saudi Arabia"). It is whole-word, so near-misses do NOT
match — notably "Romania" (which contains the substring "OMAN") and Middle-East
non-members like Israel, Turkey, and Egypt.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import GCC_COUNTRIES_FILE

FLAG_COL = "gcc_billing"
COUNTRY_COL = "gcc_billing_country"


def _normalize(value: object) -> str:
    """Upper-case, strip punctuation to spaces, collapse whitespace."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def load_gcc_countries(
    path: Path | str = GCC_COUNTRIES_FILE,
) -> list[tuple[str, tuple[str, ...]]]:
    """Read the reference list -> [(canonical_country, normalized_aliases)]."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"GCC country reference list not found: {path}")

    countries: list[tuple[str, tuple[str, ...]]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name == "country":
                continue
            raw_aliases = row[1] if len(row) > 1 else ""
            aliases = tuple(
                a for a in (_normalize(p) for p in raw_aliases.split(";")) if a
            )
            if aliases:
                countries.append((name, aliases))
    return countries


def match_country(
    value: object, countries: list[tuple[str, tuple[str, ...]]]
) -> tuple[bool, str | None]:
    """Return (is_gcc, canonical_country) for one billing-country value."""
    norm = _normalize(value)
    if not norm:
        return False, None
    haystack = f" {norm} "
    for canonical, aliases in countries:
        for alias in aliases:
            if f" {alias} " in haystack:
                return True, canonical
    return False, None


def flag_gcc_billing(
    df: pd.DataFrame,
    countries: list[tuple[str, tuple[str, ...]]] | None = None,
    country_col: str = "LATEST_BILLING_ADDRESS4",
    shipping_country_col: str = "LATEST_SHIPPING_ADDRESS4",
) -> pd.DataFrame:
    """Add GCC flag + canonical-country columns. Checks billing then shipping."""
    if countries is None:
        countries = load_gcc_countries()

    out = df.copy()
    n = len(out)
    billing = out[country_col] if country_col in out.columns else pd.Series([None] * n, index=out.index)
    shipping = (
        out[shipping_country_col]
        if shipping_country_col in out.columns
        else pd.Series([None] * n, index=out.index)
    )

    def _match(b, s):
        hit, country = match_country(b, countries)
        if hit:
            return True, country
        return match_country(s, countries)

    results = [_match(b, s) for b, s in zip(billing.tolist(), shipping.tolist())]
    out[FLAG_COL] = [hit for hit, _ in results]
    out[COUNTRY_COL] = [country for _, country in results]
    return out
