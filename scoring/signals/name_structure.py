"""Name-structure signal — DELIBERATELY WEAK, corroboration-only.

============================ SENSITIVE SIGNAL ============================
This detects purely STRUCTURAL, factual features of a name:
  - a hyphenated / double-barrelled surname (e.g. "Pelham-Clinton")
  - optionally, a multi-part construction (4+ name tokens) — OFF by default
It does NOT judge whether a name "sounds" upper-class, and it deliberately does
NOT infer ethnicity, nationality, or origin. There are no language lists and no
nobiliary-particle lists (de / von / van / di / da ...), because those are
national-origin / language markers — detecting them would systematically score
ordinary-status customers from many backgrounds (e.g. Hispanic "de la ...",
Dutch/Vietnamese "van ...", Portuguese "dos ...") as "heritage wealth", which is
both unfair (disparate impact by origin) and contrary to the no-origin rule.

WHY IT IS WEIGHTED AT THE FLOOR AND GATED BEHIND CORROBORATION:
  - Name structure is at best a faint, noisy correlate of heritage wealth.
  - Even purely structural features skew by ordinary naming convention, so on its
    own this would nudge unrelated customers.
This signal MUST NEVER be the sole basis for flagging, grading, or any
customer-facing action. The combiner (see SUPPORTING_SIGNALS in combine.py) only
counts it when at least one STRONGER signal has already fired, and its weight is
a single knob — SIGNAL_WEIGHTS["name_structure"] — that you can lower or set to 0
to switch it off entirely.
=========================================================================
"""
from __future__ import annotations

import re

import pandas as pd

FLAG_COL = "name_structure"
REASON_COL = "name_structure_reason"

# Honest, hedged — never "aristocratic name".
REASON = "name structure is a weak, possible heritage-wealth indicator (corroborating only)"

# A surname joined by an internal hyphen, with a letter on each side so stray
# punctuation or a dangling hyphen never matches.
_HYPHENATED = re.compile(r"[A-Za-z]+-[A-Za-z]+")


def _name_parts(name: object) -> list[str]:
    """Whitespace-separated name tokens, dropping single-letter initials."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return []
    cleaned = re.sub(r"[^A-Za-z'\- ]+", " ", str(name)).strip()
    return [t for t in cleaned.split() if len(t.strip(".'-")) > 1]


def detect_structure(name: object, include_multipart: bool = False) -> tuple[bool, str | None]:
    """Return (matched, reason) for purely structural name features.

    Default = hyphenation only (the cleanest, least origin-skewed marker).
    ``include_multipart`` additionally flags 4+ token names, but that over-fires
    on multi-surname naming conventions, so it is opt-in and documented as noisy.
    """
    parts = _name_parts(name)
    if not parts:
        return False, None
    if any(_HYPHENATED.search(p) for p in parts):
        return True, REASON
    if include_multipart and len(parts) >= 4:
        return True, REASON
    return False, None


def flag_name_structure(
    df: pd.DataFrame, name_col: str = "Name", include_multipart: bool = False
) -> pd.DataFrame:
    """Add the (weak, structural) name-structure flag + hedged reason columns."""
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[name_col].apply(lambda n: detect_structure(n, include_multipart))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
