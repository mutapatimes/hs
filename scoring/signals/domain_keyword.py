"""High-earning domain-keyword signal — three tiers.

A stronger cousin of custom_email: when a customer's CUSTOM email domain contains
a high-earning-industry keyword, the owner almost certainly works at / owns a
finance or professional-services firm — much higher-earning than a generic vanity
domain. Three tiers (per-match weight, like delivery_venue's FBO/marina override):

  - ELITE finance (elite_finance_keywords.csv): private equity / hedge fund /
    family office / sovereign wealth -> weight 3 (like a named wealth employer).
  - TALENT / ARTIST MANAGEMENT (talent_mgmt_keywords.csv): "mgmt" and talent-agency
    compounds in the domain, the email's local part, or the company field — the
    customer is likely represented talent (artist, designer, musician, model) or
    their agent ordering on their behalf -> weight 3.
  - GENERAL high-earning (high_earning_keywords.csv): capital, ventures, equity,
    partners, advisory, wealth, holdings, ... -> weight 2.

Domain tiers fire only on CUSTOM domains (reuses custom_email's excluded set); the
talent LOCAL-PART check ("mgmt@artist.com", "sarahmgmt@gmail.com") works on any
domain, because a management inbox is the tell regardless of the provider.
Combine.py groups this with custom_email so a keyword domain isn't credited twice,
and reads the per-row type from TYPE_COL to pick the weight.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import (ELITE_FINANCE_KEYWORDS_FILE, HIGH_EARNING_KEYWORDS_FILE,
                    TALENT_MGMT_KEYWORDS_FILE)
from scoring.signals.custom_email import _email_domain, _is_excluded, load_excluded

FLAG_COL = "domain_keyword"
REASON_COL = "domain_keyword_reason"
TYPE_COL = "domain_keyword_type"

# Segments that END WITH a keyword by coincidence, not as a finance tell
# (adventures->"ventures", commonwealth->"wealth").
_STOPLIST = {"adventures", "adventure", "misadventures", "misadventure", "commonwealth"}

# "…mgmt" compounds that are ordinary business functions, NOT talent management.
_MGMT_STOPLIST = {
    "propertymgmt", "projectmgmt", "assetmgmt", "riskmgmt", "wealthmgmt", "fundmgmt",
    "facilitymgmt", "facilitiesmgmt", "eventmgmt", "wastemgmt", "itmgmt", "datamgmt",
    "casemgmt", "energymgmt", "constructionmgmt", "fleetmgmt", "supplymgmt",
}


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


def _talent_hit(segs: list[str], kw: str) -> bool:
    """Talent keyword as a whole segment or ANY-length suffix ("sallyclarkemgmt").

    The curated talent list is suffix-safe (no ordinary word ends in "mgmt"), so the
    >=6-char guard is unnecessary; non-talent compounds are stoplisted instead.
    """
    for seg in segs:
        if seg in _MGMT_STOPLIST:
            continue
        if seg == kw or seg.endswith(kw):
            return True
    return False


def match_domain(email: object, general, elite, excluded,
                 talent=()) -> tuple[bool, str | None, str | None]:
    """Return (hit, 'keyword in domain', tier) — 'elite', then 'talent', then 'general'."""
    domain = _email_domain(email)
    if domain is None or "." not in domain or _is_excluded(domain, excluded):
        return False, None, None
    for label in domain.split(".")[:-1]:                 # every label except TLD
        segs = [s for s in re.split(r"[^a-z0-9]+", label) if s]
        flat = "".join(segs)                             # de-hyphenated whole label
        for kw in elite:                                 # compound -> also match flat suffix
            if _seg_hit(segs, kw) or (len(kw) >= 6 and flat.endswith(kw)):
                return True, f'"{kw}" in {domain} (elite finance)', "elite"
        for kw in talent:
            if _talent_hit(segs, kw) or (flat not in _MGMT_STOPLIST and flat.endswith(kw)):
                return True, f'"{kw}" in {domain} (talent / artist management)', "talent"
        for kw in general:
            if _seg_hit(segs, kw):
                return True, f'"{kw}" in {domain}', "general"
    return False, None, None


def match_local_mgmt(email: object) -> tuple[bool, str | None, str | None]:
    """A management inbox in the email's LOCAL PART ("mgmt@artist.com", "sarahmgmt@gmail.com").

    Works on ANY domain, including free providers: an agent running the talent's orders from a
    management mailbox is the tell regardless of where the mailbox is hosted. Non-talent
    "…mgmt" compounds (propertymgmt, projectmgmt, ...) are stoplisted.
    """
    if email is None or (isinstance(email, float) and pd.isna(email)):
        return False, None, None
    text = str(email).strip().lower()
    if "@" not in text:
        return False, None, None
    local = text.split("@", 1)[0]
    segs = [s for s in re.split(r"[^a-z0-9]+", local) if s]
    if _talent_hit(segs, "mgmt"):
        return True, '"mgmt" in email address (talent / artist management)', "talent"
    return False, None, None


def match_company(company: object, general, elite,
                  talent=()) -> tuple[bool, str | None, str | None]:
    """Same keyword tells, read from the order's COMPANY_NAME.

    A firm literally named "... Private Equity" / "... Capital Partners" is the
    same signal as a finance email domain — and "... Talent Management" / "... Mgmt"
    the same as a management email. Single-word keywords match as a whole word
    (stoplist-aware); the distinctive joined compounds (privateequity,
    familyoffice, ...) match as a substring so multi-word firm names still fire."""
    if company is None or (isinstance(company, float) and pd.isna(company)):
        return False, None, None
    norm = re.sub(r"[^a-z0-9]+", " ", str(company).lower()).strip()
    if not norm:
        return False, None, None
    segs = [s for s in norm.split() if s]
    flat = "".join(segs)
    for kw in elite:
        if _seg_hit(segs, kw) or (len(kw) >= 10 and kw in flat):
            return True, f'"{kw}" in company (elite finance)', "elite"
    for kw in talent:
        if _talent_hit(segs, kw) or (len(kw) >= 10 and kw in flat):
            return True, f'"{kw}" in company (talent / artist management)', "talent"
    for kw in general:
        if _seg_hit(segs, kw):
            return True, f'"{kw}" in company', "general"
    return False, None, None


def flag_domain_keyword(
    df: pd.DataFrame,
    general=None,
    elite=None,
    excluded=None,
    email_col: str = "EMAIL_ADDR",
    company_col: str = "COMPANY_NAME",
    talent=None,
) -> pd.DataFrame:
    """Add the domain-keyword flag + reason + tier columns to a copy of ``df``.

    Fires on a finance/talent keyword in the custom email domain, a management
    inbox in the email's local part, OR a keyword in the company field."""
    if general is None:
        general = load_keywords(HIGH_EARNING_KEYWORDS_FILE)
    if elite is None:
        elite = load_keywords(ELITE_FINANCE_KEYWORDS_FILE)
    if talent is None:
        talent = load_keywords(TALENT_MGMT_KEYWORDS_FILE)
    if excluded is None:
        excluded = load_excluded()
    out = df.copy()
    has_email = email_col in out.columns
    has_company = company_col in out.columns
    if not has_email and not has_company:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        out[TYPE_COL] = None
        return out

    emails = out[email_col] if has_email else pd.Series([None] * len(out), index=out.index)
    companies = out[company_col] if has_company else pd.Series([None] * len(out), index=out.index)
    flags, reasons, types = [], [], []
    for email, company in zip(emails.tolist(), companies.tolist()):
        hit, reason, tier = match_domain(email, general, elite, excluded, talent)
        if not hit:
            hit, reason, tier = match_local_mgmt(email)
        if not hit:
            hit, reason, tier = match_company(company, general, elite, talent)
        flags.append(hit)
        reasons.append(reason)
        types.append(tier)
    out[FLAG_COL] = flags
    out[REASON_COL] = reasons
    out[TYPE_COL] = types
    return out
