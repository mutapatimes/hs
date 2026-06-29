"""Elite-university alumni email signal.

Flags customers whose email is at an Ivy League / elite-university alumni or
graduate-school domain (reference_data/domains/elite_alumni_domains.csv) —
post.harvard.edu, stanfordalumni.org, wharton.upenn.edu, etc. Reuses the
work-email domain matcher (domain + subdomain), so the same robustness applies.
"""
from __future__ import annotations

import pandas as pd

from config import ELITE_ALUMNI_FILE
from scoring.signals.work_email import load_domains, match_email

FLAG_COL = "elite_alumni"
REASON_COL = "elite_alumni_reason"


def flag_elite_alumni(
    df: pd.DataFrame,
    domains: dict[str, tuple[str, str]] | None = None,
    email_col: str = "EMAIL_ADDR",
) -> pd.DataFrame:
    """Add elite-alumni flag + reason columns to a copy of ``df``."""
    if domains is None:
        domains = load_domains(ELITE_ALUMNI_FILE)
    out = df.copy()
    if email_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[email_col].apply(lambda e: match_email(e, domains))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
