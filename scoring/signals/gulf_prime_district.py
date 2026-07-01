"""Prime Gulf district signal (Bucket 3 of the geography taxonomy) — GATED, off by default.

Flags customers whose billing/shipping address is in a prime Gulf residential district —
Palm Jumeirah, Emirates Hills, Downtown Dubai, the Riyadh Diplomatic Quarter, and peers
(reference_data/locations/gulf_prime_districts.csv + gulf_prime_postcodes.csv). These are
genuinely among the most expensive residential districts on earth with internationally-mixed
residents, so the tell is arguably property wealth — but in a UK book a district-level Gulf
signal still disproportionately touches Middle-Eastern clients, so the Recital-71 effect test
isn't as clean as Monaco's. It therefore lives in the GATED tier (scoring.combine.
ORIGIN_PROXY_SIGNALS): a tenant with a documented Gulf clientele opts in via
include_origin=True; everyone else's default stays clean.

Reuses the existing matchers rather than reimplementing them: name matching + country guard
from ``hnw_area``, and country-guarded postcode matching from ``intl_postcode``. The list is
sourced from residential property-market data, not a tax list; the reason text stays factual.
See docs/geography-signal-taxonomy.md.
"""
from __future__ import annotations

import pandas as pd

from config import GULF_PRIME_DISTRICTS_FILE, GULF_PRIME_POSTCODES_FILE
from scoring.signals import hnw_area, intl_postcode
from scoring.signals.delivery_venue import load_venues

FLAG_COL = "gulf_prime_district"
REASON_COL = "gulf_prime_district_reason"


def load_districts(path=GULF_PRIME_DISTRICTS_FILE):
    return load_venues(path)


def load_gulf_postcodes(path=GULF_PRIME_POSTCODES_FILE):
    return intl_postcode.load_postcodes(path)


def flag_gulf_prime_district(df: pd.DataFrame, areas=None, postcodes=None) -> pd.DataFrame:
    """Add gulf_prime_district flag + factual reason columns to a copy of ``df``.

    A row fires if its address names a prime Gulf district (name match, country-guarded) OR
    its postcode falls in a prime Gulf prefix (country-guarded). Name match wins the reason.
    """
    if areas is None:
        areas = load_districts()
    if postcodes is None:
        postcodes = load_gulf_postcodes()

    by_name = hnw_area.flag_hnw_area(df, areas=areas)
    by_pc = intl_postcode.flag_intl_postcode(df, rows=postcodes)

    out = df.copy()
    flags, reasons = [], []
    for i in range(len(out)):
        if bool(by_name[hnw_area.MATCH_COL].iloc[i]):
            area = by_name[hnw_area.AREA_COL].iloc[i]
            country = by_name[hnw_area.TYPE_COL].iloc[i]
            flags.append(True)
            reasons.append(f"{area} — prime residential district ({country})")
        elif bool(by_pc[intl_postcode.FLAG_COL].iloc[i]):
            flags.append(True)
            reasons.append(f"{by_pc[intl_postcode.REASON_COL].iloc[i]} — prime residential district")
        else:
            flags.append(False)
            reasons.append(None)
    out[FLAG_COL] = flags
    out[REASON_COL] = reasons
    return out
