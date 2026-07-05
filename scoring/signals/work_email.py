"""Work-email-domain signal.

Flags customers whose email is at a wealth-signalling employer — banks,
private equity, hedge funds, wealth managers, family offices — defined by an
editable reference list (see reference_data/domains/wealth_employer_domains.csv).

Subdomains match their parent (e.g. john@emea.gs.com matches gs.com), but
unrelated domains do not (e.g. notgs.com never matches gs.com).

It also reads the order's COMPANY_NAME: a customer on a free email whose order
carries a wealth-employer name ("Goldman Sachs", "Rothschild & Co") is the same
tell as the work email. Only distinctive employer names are matched from the
company field (multi-word firms, or single tokens of 5+ chars) to avoid
false positives on short/ambiguous names.
"""
from __future__ import annotations

import csv
import re
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


def _norm_company(value: object) -> str:
    """Upper-case, alnum-token form padded with spaces for whole-phrase matching."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    t = re.sub(r"\s+", " ", t).strip()
    return f" {t} " if t else ""


def employer_names(domains: dict[str, tuple[str, str]]) -> list[tuple[str, str]]:
    """Distinctive employer names to match in the COMPANY_NAME field, longest first.

    Only names that are unlikely to collide in free text: multi-token firms, or a
    single token of 5+ characters (so "UBS"/"GS" are skipped, "Barclays"/"Goldman
    Sachs"/"Rothschild" are kept)."""
    seen: dict[str, str] = {}
    for org, _cat in domains.values():
        norm = re.sub(r"[^A-Z0-9]+", " ", (org or "").upper()).strip()
        if not norm:
            continue
        toks = norm.split()
        if len(toks) >= 2 or (len(toks) == 1 and len(toks[0]) >= 5):
            seen.setdefault(norm, org)
    return sorted(seen.items(), key=lambda kv: -len(kv[0]))


def match_company(company: object, names: list[tuple[str, str]]) -> tuple[bool, str | None]:
    """Return (is_wealth_employer, reason) from a company-name match."""
    hay = _norm_company(company)
    if not hay:
        return False, None
    for norm, org in names:
        if f" {norm} " in hay:
            return True, f"{org} (company field)"
    return False, None


def flag_work_email(
    df: pd.DataFrame,
    domains: dict[str, tuple[str, str]] | None = None,
    email_col: str = "EMAIL_ADDR",
    company_col: str = "COMPANY_NAME",
) -> pd.DataFrame:
    """Add work-email flag + reason columns to a copy of ``df``.

    Fires on a wealth-employer email domain OR the same employer named in the
    order's company field."""
    if domains is None:
        domains = load_domains()

    out = df.copy()
    has_email = email_col in out.columns
    has_company = company_col in out.columns
    if not has_email and not has_company:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out

    names = employer_names(domains) if has_company else []
    emails = out[email_col] if has_email else pd.Series([None] * len(out), index=out.index)
    companies = out[company_col] if has_company else pd.Series([None] * len(out), index=out.index)

    flags, reasons = [], []
    for email, company in zip(emails.tolist(), companies.tolist()):
        hit, reason = match_email(email, domains)
        if not hit:
            hit, reason = match_company(company, names)
        flags.append(hit)
        reasons.append(reason)
    out[FLAG_COL] = flags
    out[REASON_COL] = reasons
    return out
