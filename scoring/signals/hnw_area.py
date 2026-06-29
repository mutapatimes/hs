"""International HNW-area signal (name-based).

Flags customers whose BILLING or SHIPPING address names a high-net-worth
neighbourhood, town, or district anywhere in the world — Monaco, Gstaad,
Roppongi, Palm Jumeirah, Forte dei Marmi, etc. (reference_data/locations/
hnw_areas.csv). Matching names (not postcodes) is robust across countries whose
postal formats differ wildly, and is the right tool for places like the GCC
where postcodes are barely used.

Reuses the venue matcher (whole-word, punctuation-insensitive) so an ordinary
street that merely contains a place word doesn't false-fire.
"""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

from config import HNW_AREAS_FILE
from scoring.signals.delivery_venue import (
    ALL_ADDRESS_COLS,
    _combine_rows,
    load_venues,
    match_address,
)

MATCH_COL = "hnw_area_match"
AREA_COL = "hnw_area"
TYPE_COL = "hnw_area_country"

# Country columns hold the address's country in plain English ("United Kingdom").
_COUNTRY_COLS = ["LATEST_BILLING_ADDRESS4", "LATEST_SHIPPING_ADDRESS4", "ACCOUNT_ADDRESS4"]
# Map the file's short country tags to how the data spells them.
_COUNTRY_ALIASES = {"uk": "united kingdom", "uae": "united arab emirates", "usa": "united states"}


def _norm_country(value: object) -> str:
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()
    folded = re.sub(r"[^a-z0-9]+", " ", folded).strip()
    return _COUNTRY_ALIASES.get(folded, folded)


def flag_hnw_area(df: pd.DataFrame, areas=None, address_cols=None) -> pd.DataFrame:
    """Add HNW-area match, area name, and country columns to a copy of ``df``.

    COUNTRY-GUARDED: an area only counts when the address's country agrees with
    the area's country — so "Clifton" the Brighton street (United Kingdom) can't
    match Clifton, Cape Town (South Africa). When a row has no country on file,
    the name match still stands (best effort).
    """
    if areas is None:
        areas = load_venues(HNW_AREAS_FILE)
    cols = [c for c in (address_cols or ALL_ADDRESS_COLS) if c in df.columns]

    out = df.copy()
    if not cols:
        out[MATCH_COL] = False
        out[AREA_COL] = None
        out[TYPE_COL] = None
        return out

    combined = _combine_rows(out, cols)
    results = combined.apply(lambda a: match_address(a, areas)).tolist()

    # Per-row set of countries named in the address (for the guard).
    country_cols = [c for c in _COUNTRY_COLS if c in out.columns]
    norm_cols = [out[c].map(_norm_country).tolist() for c in country_cols]
    country_sets = (
        [set(filter(None, vals)) for vals in zip(*norm_cols)]
        if norm_cols else [set()] * len(out)
    )

    hits, names, countries = [], [], []
    for (hit, name, country), cset in zip(results, country_sets):
        if hit and cset and _norm_country(country) not in cset:
            hit, name, country = False, None, None  # country conflict -> reject
        hits.append(hit)
        names.append(name)
        countries.append(country)
    out[MATCH_COL] = hits
    out[AREA_COL] = names
    out[TYPE_COL] = countries
    return out
