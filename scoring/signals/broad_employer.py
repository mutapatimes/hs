"""Broad-employer-domain signal — corroboration-only, low weight.

Big tech, enterprise software and energy majors employ hundreds of thousands of people
across the whole pay spectrum, so a work email at one is a WEAK per-capita wealth tell.
Unlike ``work_email`` (which can originate a score), this signal is corroboration-only:
listed in ``SUPPORTING_SIGNALS`` (scoring.combine), so the gate there neutralises it
unless a stronger, non-supporting signal has ALSO fired. It never surfaces a customer on
its own; it only nudges the ranking of someone already flagged.

The matching machinery is shared with ``work_email`` (email domain incl. subdomains, plus
the order's COMPANY_NAME); only the reference list and the output columns differ.
"""
from __future__ import annotations

import pandas as pd

from config import BROAD_EMPLOYER_DOMAINS_FILE
from scoring.signals.work_email import (
    employer_names,
    load_domains as _load_domains,
    match_company,
    match_email,
)

FLAG_COL = "broad_employer"
REASON_COL = "broad_employer_reason"


def load_domains(path=BROAD_EMPLOYER_DOMAINS_FILE) -> dict[str, tuple[str, str]]:
    """Read the broad-employer reference list -> {domain: (organisation, category)}."""
    return _load_domains(path)


def flag_broad_employer(
    df: pd.DataFrame,
    domains: dict[str, tuple[str, str]] | None = None,
    email_col: str = "EMAIL_ADDR",
    company_col: str = "COMPANY_NAME",
) -> pd.DataFrame:
    """Add the broad-employer flag + reason columns to a copy of ``df``.

    Fires on a broad-employer email domain OR the same employer named in the order's
    company field, exactly like ``work_email`` but against the broad-employer list."""
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
