"""Work-email-domain signal.

Flags customers whose email is at a wealth-signalling employer — banks,
private equity, hedge funds, wealth managers, family offices — defined by an
editable reference list (see reference_data/domains/wealth_employer_domains.csv).

Subdomains match their parent (e.g. john@emea.gs.com matches gs.com), but
unrelated domains do not (e.g. notgs.com never matches gs.com).
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from config import WEALTH_DOMAINS_FILE

FLAG_COL = "work_email"
REASON_COL = "work_email_reason"


def _email_domain(value: object) -> str | None:
    """Return the lower-cased domain part of an email, or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip()
    return domain or None


def load_domains(
    path: Path | str = WEALTH_DOMAINS_FILE,
) -> dict[str, tuple[str, str]]:
    """Read the reference list -> {domain: (organisation, category)}.

    Skips comment lines (starting with '#'), blanks, and the header.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Wealth-domain reference list not found: {path}")

    domains: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            domain = row[0].strip().lower()
            if not domain or domain.startswith("#") or domain == "domain":
                continue
            org = row[1].strip() if len(row) > 1 else ""
            category = row[2].strip() if len(row) > 2 else ""
            domains[domain] = (org, category)
    return domains


def _reason(org: str, category: str, domain: str) -> str:
    """Build a human-readable reason like 'Goldman Sachs (banking)'."""
    label = org or domain
    return f"{label} ({category})" if category else label


def match_email(
    email: object, domains: dict[str, tuple[str, str]]
) -> tuple[bool, str | None]:
    """Return (is_wealth_employer, reason). Matches exact domain or subdomain."""
    domain = _email_domain(email)
    if domain is None:
        return False, None

    # Check the full domain, then progressively drop left-most labels so a
    # subdomain (emea.gs.com) still matches its parent (gs.com).
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in domains:
            org, category = domains[candidate]
            return True, _reason(org, category, candidate)
    return False, None


def flag_work_email(
    df: pd.DataFrame,
    domains: dict[str, tuple[str, str]] | None = None,
    email_col: str = "EMAIL_ADDR",
) -> pd.DataFrame:
    """Add work-email flag + reason columns to a copy of ``df``."""
    if domains is None:
        domains = load_domains()

    out = df.copy()
    if email_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[email_col].apply(lambda e: match_email(e, domains))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
