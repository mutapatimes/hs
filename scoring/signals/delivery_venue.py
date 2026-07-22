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


# Words that name a KIND of place rather than a particular one. An alias built ONLY from these
# ("Grand Hotel", "The Park") fires on ordinary streets and buildings.
_PLACE_KIND = frozenset("""
    HOTEL HOTELS RESORT RESORTS RESIDENCE RESIDENCES APARTMENT APARTMENTS SUITE SUITES PENTHOUSE
    HOUSE COURT PLACE PLAZA TOWER TOWERS PARK GARDEN GARDENS SQUARE STREET ROAD AVENUE LANE
    MANOR HALL LODGE VILLA PALACE CASTLE ESTATE CLUB SPA MARINA HARBOUR HARBOR PORT QUAY
    BEACH ISLAND BAY GRAND ROYAL IMPERIAL CENTRAL PRIVATE LUXURY THE OF AND
    AIRPORT TERMINAL HANGAR JET YACHT MARINE JETTY BERTH INTERNATIONAL NATIONAL GLOBAL
""".split())

# Words that really do name a venue but collide badly ON THEIR OWN — the reference file's "bad:
# MANDARIN (-> Mandarin Plaza)" warning. Perfectly good inside a longer alias, never alone.
_AMBIGUOUS_ALONE = frozenset("""
    MANDARIN ORIENTAL PENINSULA SAVOY CONNAUGHT BERKELEY GORING DORCHESTER LANGHAM METROPOLE
    RITZ BRISTOL CARLTON EDEN EXCELSIOR PLAZA REGENT WALDORF WESTBURY BEAUMONT ATHENAEUM
    CADOGAN CHILTERN MARYLEBONE MAYFAIR CHELSEA BELGRAVIA KNIGHTSBRIDGE
""".split())
_MIN_SOLO_ALIAS = 7        # a one-word alias must be a long, distinctive proper noun


def usable_alias(norm: str) -> bool:
    """Whether a normalised alias is specific enough to look for inside a delivery address.

    Specificity comes from length as well as from wording, so the bar loosens as the phrase grows:

    * one word  — the risky shape. Must be long, not a kind-of-place word, and not a word that
      collides on its own ("Mandarin" reaches Mandarin Plaza; "Lanesborough" reaches nothing else).
    * two words — must name something in particular: "Mandarin Oriental" yes, "Grand Hotel" no.
    * three or more — specific enough as a whole phrase, even when every word is ordinary
      ("Royal Garden Hotel" is a real hotel and matches nothing else).

    Every alias currently shipped passes. This is the guard that stops a future addition, written
    by hand or generated, from firing on an ordinary street — which the reference file has always
    warned about but nothing enforced.
    """
    toks = norm.split()
    if not toks:
        return False
    if len(toks) == 1:
        return len(toks[0]) >= _MIN_SOLO_ALIAS and toks[0] not in _AMBIGUOUS_ALONE \
            and toks[0] not in _PLACE_KIND
    if len(toks) == 2:
        return any(t not in _PLACE_KIND for t in toks)
    return True


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


def load_venues(path: Path | str = SIGNAL_VENUES_FILE, alias_guard=None) -> list[Venue]:
    """Read the reference list into normalized Venue records.

    ``alias_guard`` is an optional predicate applied to each normalised alias. It is OFF by
    default because this loader is shared by several tables with different risks: the signal-venue
    list holds hotel and club names that have to be spotted inside a full street address, where a
    loose alias fires on every neighbour, while the area, prime-residence, wealth-structure and
    district lists hold place names that are legitimately short ("Gstaad", "Davos"). Only the
    caller knows which it is reading, so only the caller opts in.
    """
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
                a for a in (_normalize(part) for part in raw_aliases.split(";"))
                if a and (alias_guard is None or alias_guard(a))
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
        # The venue table is the one matched inside full street addresses, so it is the one that
        # needs the collision guard the reference file has always asked for in prose.
        venues = load_venues(alias_guard=usable_alias)
    if address_cols is None:
        address_cols = DEFAULT_ADDRESS_COLS

    combined = _combine_rows(df, address_cols)
    results = combined.apply(lambda a: match_address(a, venues))
    out = df.copy()
    out[MATCH_COL] = [hit for hit, _, _ in results]
    out[VENUE_COL] = [name for _, name, _ in results]
    out[TYPE_COL] = [stype for _, _, stype in results]
    return out
