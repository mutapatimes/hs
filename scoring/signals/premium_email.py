"""Premium / "luxury ESP" email-provider signal.

Flags customers whose email is at a premium or paid email provider that skews
affluent — Apple's legacy paid mac.com, HEY, Fastmail, Superhuman, etc.
(reference_data/domains/premium_email_domains.csv). Subdomains match their parent.

Note: Superhuman is a premium email *client* over Gmail/custom domains, so it is
not detectable from an address except @superhuman.com (their staff).
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from config import PREMIUM_EMAIL_FILE

FLAG_COL = "premium_email"
REASON_COL = "premium_email_reason"


def _email_domain(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip()
    return domain or None


def load_providers(path: Path | str = PREMIUM_EMAIL_FILE) -> dict[str, str]:
    """Read the reference list -> {domain: provider_label}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Premium-email reference list not found: {path}")
    providers: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            domain = row[0].strip().lower()
            if not domain or domain.startswith("#") or domain == "domain":
                continue
            providers[domain] = row[1].strip() if len(row) > 1 else domain
    return providers


def match_email(email: object, providers: dict[str, str]) -> tuple[bool, str | None]:
    """Return (is_premium, provider_label). Matches exact domain or subdomain."""
    domain = _email_domain(email)
    if domain is None:
        return False, None
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in providers:
            return True, providers[candidate]
    return False, None


def flag_premium_email(
    df: pd.DataFrame,
    providers: dict[str, str] | None = None,
    email_col: str = "EMAIL_ADDR",
) -> pd.DataFrame:
    """Add premium-email flag + provider columns to a copy of ``df``."""
    if providers is None:
        providers = load_providers()
    out = df.copy()
    if email_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[email_col].apply(lambda e: match_email(e, providers))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
