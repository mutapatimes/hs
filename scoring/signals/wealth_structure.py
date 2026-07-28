"""Wealth-management structure signal (Bucket 2 of the geography taxonomy).

Flags customers whose billing/shipping address is routed through a wealth-management
structure — a trust company, family office, corporate registered agent, fiduciary, or an
offshore PO box (reference_data/addresses/wealth_structures.csv). The tell isn't geography,
it's that a human being's shopping is being routed through a wealth structure — arguably a
stronger signal than the address itself, and crucially ORIGIN-NEUTRAL, so it is ON by
default. It pairs naturally with the household-linkage work (shared_phone).

Named structures (trust company / family office / registered agent / fiduciary) are specific
enough to fire alone. A bare "PO Box" is far too common on its own, so it only fires when it
co-occurs with an offshore jurisdiction (the incorporation territories dropped from the
Bucket-1 residential list). Reason text stays factual; see docs/geography-signal-taxonomy.md.
"""
from __future__ import annotations

import pandas as pd

from config import WEALTH_STRUCTURES_FILE
from scoring.signals.delivery_venue import (
    ALL_ADDRESS_COLS,
    _combine_rows,
    _normalize,
    load_venues,
    match_address,
)

FLAG_COL = "wealth_structure"
TYPE_COL = "wealth_structure_type"
REASON_COL = "wealth_structure_reason"

# Offshore incorporation / registered-agent jurisdictions that turn a bare "PO Box" into a
# structural tell. A PO box in one of these is a company-formation / fiduciary address, not a home
# — even where the territory is also prime-residential (Cayman, Bermuda, the Crown dependencies sit
# in the Bucket-1 residential list too; the PO-box qualifier is what makes this the structural read,
# and the two signals co-fire harmlessly). Tokens are in _normalize()'s uppercase/space form; each
# maps to the display name used in the reason, so multi-word territories read cleanly.
_OFFSHORE = {
    "BRITISH VIRGIN ISLANDS": "British Virgin Islands", "BVI": "British Virgin Islands",
    "TORTOLA": "British Virgin Islands", "ROAD TOWN": "British Virgin Islands",
    "CAYMAN ISLANDS": "Cayman Islands", "CAYMAN": "Cayman Islands",
    "PANAMA": "Panama", "SEYCHELLES": "Seychelles", "MAURITIUS": "Mauritius", "BERMUDA": "Bermuda",
    "BAHAMAS": "Bahamas",
    "TURKS AND CAICOS": "Turks and Caicos", "ANGUILLA": "Anguilla",
    "COOK ISLANDS": "Cook Islands", "NEVIS": "Nevis", "ST KITTS AND NEVIS": "Nevis",
    "BELIZE": "Belize", "MARSHALL ISLANDS": "Marshall Islands", "GIBRALTAR": "Gibraltar",
    "ISLE OF MAN": "Isle of Man", "GUERNSEY": "Guernsey", "JERSEY": "Jersey",
    "LIECHTENSTEIN": "Liechtenstein", "VADUZ": "Liechtenstein",
    "CURACAO": "Curacao", "LABUAN": "Labuan", "VANUATU": "Vanuatu",
}

# Some single-word tokens collide with well-known (often affluent) US places — a false "offshore"
# flag on a Long Island or Florida client is exactly the kind of error that discredits the signal.
# Each collision lists the phrase(s) in which the token does NOT mean the territory. We blank those
# phrases out, then only fire if the token still stands alone somewhere else — so "Panama City,
# Panama" fires on the trailing country while "Panama City, FL" does not, and "St Helier, Jersey"
# fires while "Newark, New Jersey" does not. ("Nassau" is dropped outright: Nassau County, NY is far
# more common than the Bahamian capital, which anyway carries "Bahamas" in the address.)
_OFFSHORE_EXCLUDE = {
    "JERSEY": ("NEW JERSEY",),
    "PANAMA": ("PANAMA CITY",),       # PANAMA CITY BEACH is caught by the same prefix
    "BERMUDA": ("BERMUDA DUNES",),
}


def _has_pobox(norm: str) -> bool:
    padded = f" {norm} "
    return " PO BOX " in padded or " P O BOX " in padded


def _offshore_hit(norm: str) -> str | None:
    padded = f" {norm} "
    for tok, display in _OFFSHORE.items():
        haystack = padded
        for phrase in _OFFSHORE_EXCLUDE.get(tok, ()):
            haystack = haystack.replace(f" {phrase} ", " ")
        if f" {tok} " in haystack:
            return display
    return None


def flag_wealth_structure(df: pd.DataFrame, venues=None, address_cols=None) -> pd.DataFrame:
    """Add wealth_structure flag + type + factual reason columns to a copy of ``df``."""
    if venues is None:
        venues = load_venues(WEALTH_STRUCTURES_FILE)
    cols = [c for c in (address_cols or ALL_ADDRESS_COLS) if c in df.columns]

    out = df.copy()
    if not cols:
        out[FLAG_COL] = False
        out[TYPE_COL] = None
        out[REASON_COL] = None
        return out

    combined = _combine_rows(out, cols)
    flags, types, reasons = [], [], []
    for addr in combined.tolist():
        hit, name, stype = match_address(addr, venues)
        if hit:
            flags.append(True)
            types.append(stype)
            reasons.append(f"Address routed through a {name}")
            continue
        norm = _normalize(addr)
        offshore = _offshore_hit(norm) if _has_pobox(norm) else None
        if offshore:
            flags.append(True)
            types.append("offshore_pobox")
            reasons.append(f"Address is an offshore PO box ({offshore})")
        else:
            flags.append(False)
            types.append(None)
            reasons.append(None)
    out[FLAG_COL] = flags
    out[TYPE_COL] = types
    out[REASON_COL] = reasons
    return out
