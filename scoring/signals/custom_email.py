"""Custom email-domain signal (deliberately WEAK).

Flags customers whose email is on a CUSTOM / vanity domain — i.e. not a free
consumer provider (gmail, yahoo, ...), not a premium provider (premium_email),
and not a known wealth employer (work_email). Owning your own domain is a mild
status/affluence tell, but it's noisy (small businesses, hobby sites, etc.), so
it is weighted VERY LOW: "flag all, rank low". It is strongest as corroboration
when a stronger signal also fires.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from config import (
    ELITE_ALUMNI_FILE,
    FREE_EMAIL_FILE,
    HOTEL_CHAIN_DOMAINS_FILE,
    HOTEL_DOMAINS_FILE,
    PREMIUM_EMAIL_FILE,
    STYLING_SERVICES_FILE,
    WEALTH_DOMAINS_FILE,
)

FLAG_COL = "custom_email"
REASON_COL = "custom_email_reason"


def _email_domain(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip()
    return domain or None


def _load_domain_column(path: Path | str) -> set[str]:
    """Read the first column of a domains CSV into a lower-cased set."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Domain reference list not found: {path}")
    out: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            domain = row[0].strip().lower()
            if not domain or domain.startswith("#") or domain == "domain":
                continue
            out.add(domain)
    return out


def load_excluded() -> set[str]:
    """Domains already classified elsewhere: free, premium, employer, alumni."""
    return (
        _load_domain_column(FREE_EMAIL_FILE)
        | _load_domain_column(PREMIUM_EMAIL_FILE)
        | _load_domain_column(WEALTH_DOMAINS_FILE)
        | _load_domain_column(ELITE_ALUMNI_FILE)
        | _load_domain_column(HOTEL_DOMAINS_FILE)
        | _load_domain_column(HOTEL_CHAIN_DOMAINS_FILE)
        | _load_domain_column(STYLING_SERVICES_FILE)
    )


def _is_excluded(domain: str, excluded: set[str]) -> bool:
    """True if the domain or any parent suffix is in the excluded set."""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in excluded:
            return True
    return False


def match_email(email: object, excluded: set[str]) -> tuple[bool, str | None]:
    """Return (is_custom_domain, domain). Needs a dotted domain not in ``excluded``."""
    domain = _email_domain(email)
    if domain is None or "." not in domain:
        return False, None
    if _is_excluded(domain, excluded):
        return False, None
    return True, domain


def flag_custom_email(
    df: pd.DataFrame,
    excluded: set[str] | None = None,
    email_col: str = "EMAIL_ADDR",
) -> pd.DataFrame:
    """Add custom-domain flag + domain columns to a copy of ``df``."""
    if excluded is None:
        excluded = load_excluded()
    out = df.copy()
    if email_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[email_col].apply(lambda e: match_email(e, excluded))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [domain for _, domain in results]
    return out
