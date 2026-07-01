"""High-value residential jurisdiction signal (Bucket 1 of the geography taxonomy).

Flags customers whose BILLING and/or SHIPPING country is a jurisdiction where residence
itself is a wealth fact — Monaco, Jersey, Guernsey, the Isle of Man, Liechtenstein and
peers (reference_data/countries/wealth_jurisdictions.csv). These are among the most
expensive residential markets on earth, with an internationally-mixed resident base, so
the correlation is with PROPERTY WEALTH, not national origin. It is therefore ON by
default (not an origin proxy) and its reason text is deliberately factual.

The list's inclusion criterion is residential property cost & exclusivity (documented in
the CSV header), NOT any OECD/EU tax list — and the reason never says "tax haven" or
"offshore". See docs/geography-signal-taxonomy.md. Reuses the whole-word country matcher
from the GCC signal, so "Romania" never matches, and records which field (billing/
shipping) triggered.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from config import WEALTH_JURISDICTIONS_FILE
from scoring.signals.gcc_billing import match_country

FLAG_COL = "wealth_jurisdiction"
REASON_COL = "wealth_jurisdiction_reason"

BILLING_COUNTRY_COL = "LATEST_BILLING_ADDRESS4"
SHIPPING_COUNTRY_COL = "LATEST_SHIPPING_ADDRESS4"


def load_wealth_jurisdictions(
    path: Path | str = WEALTH_JURISDICTIONS_FILE,
) -> list[tuple[str, tuple[str, ...]]]:
    """Read the reference list -> [(canonical_country, normalized_aliases)]."""
    from scoring.signals.gcc_billing import _normalize  # same normalisation

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Wealth-jurisdiction reference list not found: {path}")

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


def match_row(
    billing: object, shipping: object, countries: list[tuple[str, tuple[str, ...]]]
) -> tuple[bool, str | None]:
    """Check billing first, then shipping. Reason is factual + notes which field matched."""
    hit, country = match_country(billing, countries)
    if hit:
        return True, f"{country} — high-value residential jurisdiction (billing)"
    hit, country = match_country(shipping, countries)
    if hit:
        return True, f"{country} — high-value residential jurisdiction (shipping)"
    return False, None


def flag_wealth_jurisdiction(
    df: pd.DataFrame,
    countries: list[tuple[str, tuple[str, ...]]] | None = None,
    billing_col: str = BILLING_COUNTRY_COL,
    shipping_col: str = SHIPPING_COUNTRY_COL,
) -> pd.DataFrame:
    """Add wealth_jurisdiction flag + factual reason columns to a copy of ``df``."""
    if countries is None:
        countries = load_wealth_jurisdictions()

    out = df.copy()
    billing = out[billing_col] if billing_col in out.columns else pd.Series([None] * len(out))
    shipping = out[shipping_col] if shipping_col in out.columns else pd.Series([None] * len(out))

    results = [
        match_row(b, s, countries)
        for b, s in zip(billing.tolist(), shipping.tolist())
    ]
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
