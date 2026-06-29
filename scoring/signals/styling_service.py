"""Styling-service (B2B trade-account) signal.

Flags orders whose email is at a known STYLING / PERSONAL-SHOPPING agency
(reference_data/domains/styling_services.csv) — Threads Styling, The A List, etc.
These agencies buy on behalf of MANY UHNW clients, so a match is a recurring-
revenue B2B trade account, the highest-value thing to surface. Kept separate from
work_email so it reads "Styling service (B2B)" and gets its own recommendation
(see RECO in build_mvp.py). Reuses the work-email domain matcher.
"""
from __future__ import annotations

import pandas as pd

from config import STYLING_SERVICES_FILE
from scoring.signals.work_email import load_domains, match_email

FLAG_COL = "styling_service"
REASON_COL = "styling_service_reason"


def flag_styling_service(
    df: pd.DataFrame,
    domains: dict[str, tuple[str, str]] | None = None,
    email_col: str = "EMAIL_ADDR",
) -> pd.DataFrame:
    """Add styling-service flag + reason (the agency name) columns to a copy."""
    if domains is None:
        domains = load_domains(STYLING_SERVICES_FILE)
    out = df.copy()
    if email_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[email_col].apply(lambda e: match_email(e, domains))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
