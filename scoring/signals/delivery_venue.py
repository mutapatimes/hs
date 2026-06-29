"""Delivery-address venue signal.

Flags customers whose delivery (shipping) address is a named venue that signals
wealth — a luxury hotel, a football training ground, or a private-jet FBO —
defined by an editable reference list (reference_data/venues/signal_venues.csv).

Real delivery addresses are messy, so matching is built to survive it:
  - case-insensitive and punctuation-insensitive ("BERKLEY HOTEL - ROOM 304");
  - "c/o" / "care of" markers are stripped;
  - all address lines are searched together (the venue can be on any line);
  - a few abbreviations are expanded (HTL -> HOTEL, APT -> APARTMENT);
  - matching is whole-phrase / word-boundary, so near-misses do NOT match:
    "Bulgaria" != BULGARI, "St Moritz"/"Ritzville" != RITZ,
    "Four Seasons Park" != FOUR SEASONS HOTEL, "Connaught Drive" != THE CONNAUGHT,
    "Lairport St" != ... AIRPORT, "Luton" (town) != LUTON AIRPORT.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import SIGNAL_VENUES_FILE

MATCH_COL = "delivery_venue_match"
VENUE_COL = "delivery_venue"
TYPE_COL = "delivery_signal_type"

SHIPPING_ADDRESS_COLS = [f"LATEST_SHIPPING_ADDRESS{i}" for i in range(1, 5)] + [
    "LATEST_SHIPPING_ZIP"  # so facility postcodes (e.g. M31 4BH = Carrington) match
]
BILLING_ADDRESS_COLS = [f"LATEST_BILLING_ADDRESS{i}" for i in range(1, 5)] + [
    "LATEST_BILLING_ZIP"
]
# Address signals scan BOTH billing and shipping (someone can ship to, or be
# billed at, a wealth-signalling address). Absent columns are skipped.
ALL_ADDRESS_COLS = BILLING_ADDRESS_COLS + SHIPPING_ADDRESS_COLS
DEFAULT_ADDRESS_COLS = ALL_ADDRESS_COLS

_ABBREVIATIONS = {
    "HTL": "HOTEL",
    "APT": "APARTMENT",
    "APTS": "APARTMENT",
    "INTL": "INTERNATIONAL",
}


@dataclass(frozen=True)
class Venue:
    name: str
    signal_type: str
    aliases: tuple[str, ...]  # already normalized


def _normalize(text: object) -> str:
    """Fold accents to ASCII, upper-case, drop c/o markers + punctuation, expand abbrevs.

    Accent folding ("François" -> "FRANCOIS", "Vendôme" -> "VENDOME") lets
    international addresses match regardless of how diacritics are stored.
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").upper()
    t = re.sub(r"\bC\s*/\s*O\b", " ", t)        # "c/o", "C / O"
    t = re.sub(r"\bCARE\s+OF\b", " ", t)
    t = re.sub(r"[^A-Z0-9]+", " ", t)           # punctuation -> space
    words = (_ABBREVIATIONS.get(w, w) for w in t.split())
    return " ".join(words).strip()


def load_venues(path: Path | str = SIGNAL_VENUES_FILE) -> list[Venue]:
    """Read the reference list into normalized Venue records."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Signal-venue reference list not found: {path}")

    venues: list[Venue] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name == "venue":
                continue
            signal_type = row[1].strip() if len(row) > 1 else ""
            raw_aliases = row[2] if len(row) > 2 else ""
            aliases = tuple(
                a for a in (_normalize(part) for part in raw_aliases.split(";")) if a
            )
            if aliases:
                venues.append(Venue(name, signal_type, aliases))
    return venues


def match_address(
    address: object, venues: list[Venue]
) -> tuple[bool, str | None, str | None]:
    """Return (matched, venue_name, signal_type) for one address string."""
    norm = _normalize(address)
    if not norm:
        return False, None, None
    haystack = f" {norm} "
    for venue in venues:
        for alias in venue.aliases:
            if f" {alias} " in haystack:
                return True, venue.name, venue.signal_type
    return False, None, None


def _combine_rows(df: pd.DataFrame, address_cols: list[str]) -> pd.Series:
    """Join the address lines of each row into one searchable string."""
    present = [c for c in address_cols if c in df.columns]
    return (
        df[present]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
    )


def flag_delivery_venue(
    df: pd.DataFrame,
    venues: list[Venue] | None = None,
    address_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Add delivery-venue match, venue name, and signal-type columns."""
    if venues is None:
        venues = load_venues()
    if address_cols is None:
        address_cols = DEFAULT_ADDRESS_COLS

    combined = _combine_rows(df, address_cols)
    results = combined.apply(lambda a: match_address(a, venues))
    out = df.copy()
    out[MATCH_COL] = [hit for hit, _, _ in results]
    out[VENUE_COL] = [name for _, name, _ in results]
    out[TYPE_COL] = [stype for _, _, stype in results]
    return out
