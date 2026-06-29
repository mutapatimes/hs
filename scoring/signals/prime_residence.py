"""Prime-residence signal.

Flags customers whose BILLING address is a trophy building / branded residence
(reference_data/addresses/prime_residences.csv). Reuses the delivery-venue
matcher, just pointed at the billing address lines instead of shipping.
"""
from __future__ import annotations

import pandas as pd

from config import PRIME_RESIDENCES_FILE
from scoring.signals.delivery_venue import ALL_ADDRESS_COLS, load_venues, match_address

MATCH_COL = "prime_residence_match"
RESIDENCE_COL = "prime_residence"

# A trophy address can appear as the billing OR the shipping address.
BILLING_COLS = ALL_ADDRESS_COLS


def flag_prime_residence(df: pd.DataFrame, venues=None, address_cols=None):
    """Add prime-residence match + building-name columns to a copy of ``df``."""
    if venues is None:
        venues = load_venues(PRIME_RESIDENCES_FILE)
    cols = [c for c in (address_cols or BILLING_COLS) if c in df.columns]

    out = df.copy()
    if not cols:
        out[MATCH_COL] = False
        out[RESIDENCE_COL] = None
        return out

    combined = out[cols].fillna("").astype(str).agg(" ".join, axis=1)
    results = combined.apply(lambda a: match_address(a, venues))
    out[MATCH_COL] = [hit for hit, _, _ in results]
    out[RESIDENCE_COL] = [name for _, name, _ in results]
    return out
