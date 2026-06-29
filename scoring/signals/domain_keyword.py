"""High-earning domain-keyword signal — two tiers.

A stronger cousin of custom_email: when a customer's CUSTOM email domain contains
a high-earning-industry keyword, the owner almost certainly works at / owns a
finance or professional-services firm — much higher-earning than a generic vanity
domain. Two tiers (per-match weight, like delivery_venue's FBO/marina override):

  - ELITE finance (elite_finance_keywords.csv): private equity / hedge fund /
    family office / sovereign wealth -> weight 3 (like a named wealth employer).
  - GENERAL high-earning (high_earning_keywords.csv): capital, ventures, equity,
    partners, advisory, wealth, holdings, ... -> weight 2.

Fires only on CUSTOM domains (reuses custom_email's excluded set). Combine.py
groups it with custom_email so a finance domain isn't credited twice, and reads
the per-row type from TYPE_COL to pick the weight.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import ELITE_FINANCE_KEYWORDS_FILE, HIGH_EARNING_KEYWORDS_FILE
from scoring.signals.custom_email import _email_domain, _is_excluded, load_excluded

FLAG_COL = "domain_keyword"
REASON_COL = "domain_keyword_reason"
TYPE_COL = "domain_keyword_type"

# Segments that END WITH a keyword by coincidence, not as a finance tell
# (adventures->"ventures", commonwealth->"wealth").
_STOPLIST = {"adventures", "adventure", "misadventures", "misadventure", "commonwealth"}


def load_keywords(path: Path | str) -> list[str]:
    """Read a keyword list (lower-cased, de-duped, longest first)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Keyword list not found: {path}")
    out: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            kw = row[0].strip().lower()
            if not kw or kw.startswith("#") or kw == "keyword":
                continue
            out.add(kw)
    return sorted(out, key=len, reverse=True)


def _seg_hit(segs: list[str], kw: str) -> bool:
    """Keyword as a whole segment, or the suffix of one (>=6 chars only)."""
    for seg in segs:
        if seg in _STOPLIST:
            continue
        if seg == kw or (len(kw) >= 6 and seg.endswith(kw)):
            return True
    return False


def match_domain(email: object, general, elite, excluded) -> tuple[bool, str | None, str | None]:
    """Return (hit, 'keyword in domain', tier) — 'elite' checked before 'general'."""
    domain = _email_domain(email)
    if domain is None or "." not in domain or _is_excluded(domain, excluded):
        return False, None, None
    for label in domain.split(".")[:-1]:                 # every label except TLD
        segs = [s for s in re.split(r"[^a-z0-9]+", label) if s]
        flat = "".join(segs)                             # de-hyphenated whole label
        for kw in elite:                                 # compound -> also match flat suffix
            if _seg_hit(segs, kw) or (len(kw) >= 6 and flat.endswith(kw)):
                return True, f'"{kw}" in {domain} (elite finance)', "elite"
        for kw in general:
            if _seg_hit(segs, kw):
                return True, f'"{kw}" in {domain}', "general"
    return False, None, None


def flag_domain_keyword(
    df: pd.DataFrame,
    general=None,
    elite=None,
    excluded=None,
    email_col: str = "EMAIL_ADDR",
) -> pd.DataFrame:
    """Add the domain-keyword flag + reason + tier columns to a copy of ``df``."""
    if general is None:
        general = load_keywords(HIGH_EARNING_KEYWORDS_FILE)
    if elite is None:
        elite = load_keywords(ELITE_FINANCE_KEYWORDS_FILE)
    if excluded is None:
        excluded = load_excluded()
    out = df.copy()
    if email_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        out[TYPE_COL] = None
        return out
    results = out[email_col].apply(lambda e: match_domain(e, general, elite, excluded))
    out[FLAG_COL] = [hit for hit, _, _ in results]
    out[REASON_COL] = [reason for _, reason, _ in results]
    out[TYPE_COL] = [tier for _, _, tier in results]
    return out
