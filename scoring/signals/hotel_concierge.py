"""Hotel-concierge signal — two tiers of hotel email domain.

  - LUXURY hotels (hotel_domains.csv): ANY email fires — the whole property is
    UHNW-facing (e.g. "concierge.london@corinthia.com" or "john@aman.com").
  - Broad CHAINS (hotel_chain_domains.csv): fires ONLY for a concierge /
    guest-relations ROLE address (concierge@, guestrelations@, butler@...),
    never a personal-name email ("john.smith@marriott.com") — because those
    domains also cover hundreds of thousands of ordinary mid-market staff. The
    role itself implies a luxury property within the chain.

Kept separate from work_email so it reads "Hotel concierge", not "Work email".
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import HOTEL_CHAIN_DOMAINS_FILE, HOTEL_DOMAINS_FILE
from scoring.signals.work_email import load_domains, match_email

FLAG_COL = "hotel_concierge"
REASON_COL = "hotel_concierge_reason"

# Guest-/VIP-facing roles that imply a concierge desk even within a mega-chain.
HOTEL_ROLES = {
    "concierge", "guestservices", "guestrelations", "guestexperience",
    "butler", "frontoffice", "vip", "lifestyle", "experiences",
}


def load_chains(path: Path | str = HOTEL_CHAIN_DOMAINS_FILE) -> dict[str, str]:
    """Read {chain_domain: chain_name}."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Hotel-chain reference not found: {path}")
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            domain = row[0].strip().lower()
            if not domain or domain.startswith("#") or domain == "domain":
                continue
            out[domain] = row[1].strip() if len(row) > 1 else domain
    return out


def _split(email: object) -> tuple[str, str]:
    if email is None or (isinstance(email, float) and pd.isna(email)):
        return "", ""
    text = str(email).strip().lower()
    if "@" not in text:
        return "", ""
    local, domain = text.rsplit("@", 1)
    return local, domain.strip()


def _chain_name(domain: str, chains: dict[str, str]) -> str | None:
    """Chain name for a domain or any parent suffix (subdomain-aware)."""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in chains:
            return chains[candidate]
    return None


def match(email: object, luxury, chains) -> tuple[bool, str | None]:
    """Luxury domain -> any email; chain domain -> concierge-role email only."""
    hit, name = match_email(email, luxury)
    if hit:
        return True, name
    local, domain = _split(email)
    if domain:
        chain = _chain_name(domain, chains)
        if chain and any(seg in HOTEL_ROLES for seg in re.split(r"[._\-]+", local)):
            return True, f"{chain} (concierge desk)"
    return False, None


def flag_hotel_concierge(df: pd.DataFrame, luxury=None, chains=None, email_col: str = "EMAIL_ADDR"):
    """Add hotel-concierge flag + reason (the hotel/chain name) columns to a copy."""
    if luxury is None:
        luxury = load_domains(HOTEL_DOMAINS_FILE)
    if chains is None:
        chains = load_chains()
    out = df.copy()
    if email_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        return out
    results = out[email_col].apply(lambda e: match(e, luxury, chains))
    out[FLAG_COL] = [hit for hit, _ in results]
    out[REASON_COL] = [reason for _, reason in results]
    return out
