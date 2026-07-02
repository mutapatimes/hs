"""Origin-adjacent prime district signal (Bucket 3 of the geography taxonomy) — GATED, off by default.

Flags customers whose billing/shipping address is in a prime residential district that is
*origin-adjacent*: genuinely ultra-prime (Emirates Hills, Palm Jumeirah, the Riyadh Diplomatic
Quarter, Beirut's Achrafieh, …) but whose flagged population, as it appears in a typical UK
retailer's book, skews to a single national origin. A district-level match there is a real
property-wealth tell, yet in effect it would sort by origin (UK GDPR Recital 71, by effect not
label) — so, unlike Monaco, it lives in the GATED tier (scoring.combine.ORIGIN_PROXY_SIGNALS).

**The general review rule** (docs/geography-signal-taxonomy.md): any prime district in any location
list belongs here rather than in the on-by-default hnw_areas.csv when its flagged population skews
to one national origin in a UK book. Gulf and Lebanon are the current members; Lagos / Mumbai /
Moscow etc. go through the same test as they arise. A tenant with a documented clientele from the
region opts in (include_origin=True); everyone else's default stays clean. Lists are sourced from
residential property-market data, never a tax list; reason text stays factual.

Reuses the existing matchers rather than reimplementing them: name matching + country guard from
``hnw_area``, and country-guarded postcode matching from ``intl_postcode``.
"""
from __future__ import annotations

import pandas as pd

from config import ORIGIN_ADJACENT_DISTRICTS_FILE, ORIGIN_ADJACENT_POSTCODES_FILE
from scoring.signals import hnw_area, intl_postcode
from scoring.signals.delivery_venue import load_venues

FLAG_COL = "origin_adjacent_district"
REASON_COL = "origin_adjacent_district_reason"


def load_districts(path=ORIGIN_ADJACENT_DISTRICTS_FILE):
    return load_venues(path)


def load_district_postcodes(path=ORIGIN_ADJACENT_POSTCODES_FILE):
    return intl_postcode.load_postcodes(path)


def flag_origin_adjacent_district(df: pd.DataFrame, areas=None, postcodes=None) -> pd.DataFrame:
    """Add origin_adjacent_district flag + factual reason columns to a copy of ``df``.

    A row fires if its address names a listed prime district (name match, country-guarded) OR its
    postcode falls in a listed prefix (country-guarded). Name match wins the reason.
    """
    if areas is None:
        areas = load_districts()
    if postcodes is None:
        postcodes = load_district_postcodes()

    by_name = hnw_area.flag_hnw_area(df, areas=areas)
    by_pc = intl_postcode.flag_intl_postcode(df, rows=postcodes)

    out = df.copy()
    flags, reasons = [], []
    for i in range(len(out)):
        if bool(by_name[hnw_area.MATCH_COL].iloc[i]):
            area = by_name[hnw_area.AREA_COL].iloc[i]
            country = by_name[hnw_area.TYPE_COL].iloc[i]
            flags.append(True)
            reasons.append(f"{area} ({country})")
        elif bool(by_pc[intl_postcode.FLAG_COL].iloc[i]):
            flags.append(True)
            reasons.append(str(by_pc[intl_postcode.REASON_COL].iloc[i]))
        else:
            flags.append(False)
            reasons.append(None)
    out[FLAG_COL] = flags
    out[REASON_COL] = reasons
    return out
