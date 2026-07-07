"""Named-house signal — a street line that is a NAMED property, not a numbered address.

"The Old Rectory", "Whitfield Manor", "Chalet Eugenia": a home distinctive enough to carry a NAME
instead of a house number is a classic quiet-wealth marker (rural UK estates, alpine chalets,
Mediterranean villas). The tell is read from the customer's own billing/shipping street lines, so
there is no namesake risk — it is a CORE geo-group signal, ON by default (a wealth-address fact,
not an origin proxy), sharing diminishing returns with the other location tells.

False positives are excluded structurally, not statistically:
  - suffix keywords must be the LAST word of a comma-segment, so street names never fire
    ("Manor Road" ends in ROAD, "Hall Lane" in LANE);
  - prefix keywords (Chalet/Villa/Chateau) must be the FIRST word AND the segment must not end
    in a street suffix ("Villa Road" stays silent);
  - a segment with any digit is a numbered address, not a house name;
  - lines mentioning FLAT / APARTMENT / UNIT / SUITE / FLOOR / BLOCK are apartment addresses
    ("Flat 3, Priory Court"), not named houses.

Keywords live in reference_data/addresses/named_house_keywords.csv (operator-editable).
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

from config import NAMED_HOUSE_KEYWORDS_FILE

FLAG_COL = "named_house"
REASON_COL = "named_house_reason"

# The four raw street columns — lines 3/4 hold city/country in this schema, never street text.
STREET_COLS = [
    "LATEST_BILLING_ADDRESS1", "LATEST_BILLING_ADDRESS2",
    "LATEST_SHIPPING_ADDRESS1", "LATEST_SHIPPING_ADDRESS2",
]

# Ends-with one of these -> the segment is a STREET name, not a house name.
_STREET_SUFFIXES = {
    "ROAD", "STREET", "LANE", "AVENUE", "CLOSE", "DRIVE", "WAY", "GARDENS", "TERRACE",
    "PLACE", "MEWS", "COURT", "SQUARE", "CRESCENT", "GROVE", "HILL", "ROW", "WALK",
    "RISE", "PARADE", "GREEN", "RD", "ST", "AVE", "DR", "LN",
}

# Any of these anywhere in the line -> an apartment/unit address, not a named house.
_UNIT_WORDS = {"FLAT", "APARTMENT", "APT", "UNIT", "SUITE", "FLOOR", "BLOCK", "ROOM"}

# Word right before the suffix keyword that marks an INSTITUTIONAL building, not a home:
# "Town Hall", "Village Hall", "International Hall" (a student residence), "Masonic Lodge".
_INSTITUTIONAL_PRECEDING = {
    "TOWN", "CITY", "VILLAGE", "CHURCH", "PARISH", "SCHOOL", "COLLEGE", "UNIVERSITY",
    "STUDENT", "INTERNATIONAL", "COMMUNITY", "MEMORIAL", "SPORTS", "CONCERT", "MUSIC",
    "EXHIBITION", "CONFERENCE", "FESTIVAL", "BINGO", "MASONIC", "GUILD", "HUNTING",
}


def load_keywords(path: Path | str = NAMED_HOUSE_KEYWORDS_FILE) -> tuple[frozenset[str], frozenset[str]]:
    """Read (suffix_keywords, prefix_keywords), upper-cased."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Named-house keywords not found: {path}")
    suffix: set[str] = set()
    prefix: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            kw = row[0].strip().upper()
            if not kw or kw.startswith("#") or kw == "KEYWORD":
                continue
            pos = row[1].strip().lower() if len(row) > 1 else "suffix"
            (prefix if pos == "prefix" else suffix).add(kw)
    return frozenset(suffix), frozenset(prefix)


def _norm_segment(text: str) -> str:
    """Accent-fold, upper-case, punctuation -> space (per comma-segment)."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).strip()


def match_line(line: object, suffix: frozenset[str], prefix: frozenset[str]) -> str | None:
    """Return the matched named-house segment (title-cased) from one street line, else None."""
    if line is None or (isinstance(line, float) and pd.isna(line)):
        return None
    raw = str(line).strip()
    if not raw:
        return None
    # An apartment/unit line is never a named house, whichever segment matched.
    line_tokens = set(_norm_segment(raw).split())
    if line_tokens & _UNIT_WORDS:
        return None
    for segment in raw.split(","):
        norm = _norm_segment(segment)
        tokens = norm.split()
        if len(tokens) < 2:                      # bare "Manor" is not a named house
            continue
        if any(any(ch.isdigit() for ch in t) for t in tokens):
            continue                             # numbered = ordinary street address
        hit = ((tokens[-1] in suffix and tokens[-2] not in _INSTITUTIONAL_PRECEDING)
               or (tokens[0] in prefix and tokens[-1] not in _STREET_SUFFIXES))
        if hit:
            return " ".join(w.capitalize() for w in tokens)
    return None


def flag_named_house(df: pd.DataFrame, keywords=None) -> pd.DataFrame:
    """Add named_house flag + reason columns to a copy of ``df``."""
    if keywords is None:
        keywords = load_keywords()
    suffix, prefix = keywords
    out = df.copy()
    cols = [c for c in STREET_COLS if c in out.columns]
    if not cols:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    flags, reasons = [], []
    for _, row in out.iterrows():
        matched = None
        for col in cols:
            matched = match_line(row.get(col), suffix, prefix)
            if matched:
                break
        flags.append(matched is not None)
        reasons.append(f'Named property: "{matched}"' if matched else None)
    out[FLAG_COL] = flags
    out[REASON_COL] = reasons
    return out
