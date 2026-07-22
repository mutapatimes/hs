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

from config import EMPLOYER_ALIASES_FILE, WEALTH_DOMAINS_FILE

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
    """Build a human-readable reason like 'Goldman Sachs (private equity)'.

    The category is humanised so no internal snake_case code (wealth_management,
    hedge_fund…) reaches the client-facing reason.
    """
    from scoring.signals.type_labels import humanize_type

    label = org or domain
    human = humanize_type(category)
    return f"{label} ({human})" if human else label


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


def _norm_name(value: object) -> str:
    """Upper-case alnum-token form of an employer name, for whole-phrase comparison."""
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


def _distinctive(norm: str) -> bool:
    """Whether a name is safe to look for inside a free-text company field.

    Multi-token firms, or a single token of 5+ characters, so "UBS"/"GS" are skipped and
    "Barclays"/"Goldman Sachs"/"Rothschild" are kept."""
    toks = norm.split()
    return len(toks) >= 2 or (len(toks) == 1 and len(toks[0]) >= 5)


# Words that describe what a firm is rather than which firm it is. A canonical name from the
# hand-curated domain list may consist of one of these; a generated alias may not, because an
# alias made only of these would match half the company fields in a book.
_GENERIC_TOKENS = frozenset("""
    CAPITAL BANK BANKING GROUP PARTNERS PARTNER GLOBAL HOLDINGS HOLDING INTERNATIONAL MANAGEMENT
    ADVISORS ADVISERS ADVISORY ASSOCIATES VENTURES VENTURE EQUITY ASSET ASSETS FINANCIAL FINANCE
    SECURITIES INVESTMENTS INVESTMENT TRUST TRUSTS FUND FUNDS PRIVATE WEALTH LIMITED LTD PLC LLP
    LLC INC CORP CORPORATION COMPANY CO SERVICES SOLUTIONS CONSULTING CONSULTANTS AND THE OF
    NATIONAL FIRST ROYAL UNION STANDARD GENERAL AMERICAN EUROPEAN LONDON NEW YORK
""".split())


def _alias_ok(norm: str) -> bool:
    """A stricter bar for a generated alias than for a curated canonical name: it must be
    distinctive AND carry at least one token that names this firm rather than its industry."""
    return _distinctive(norm) and any(t not in _GENERIC_TOKENS for t in norm.split())


def load_aliases(path: Path | str = EMPLOYER_ALIASES_FILE,
                 canonical: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Read the employer-alias table as (normalised alias, canonical label) pairs.

    The table is generated offline (scripts/build_employer_aliases.py) and reviewed as a git diff,
    so this loader is the second line of defence rather than the first. Every rule below exists to
    keep a bad row inert:

    * an alias whose canonical is not already a known employer is dropped, so the table can never
      introduce an organisation the domain list does not have;
    * an alias that is not distinctive is dropped, so it cannot over-match free text;
    * an alias claimed by two different employers is dropped as ambiguous, never guessed between.

    A missing file is normal and simply means no aliases.
    """
    path = Path(path)
    if not path.exists():
        return []
    claimed: dict[str, str] = {}
    dropped: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            alias, canon = row[0].strip(), (row[1].strip() if len(row) > 1 else "")
            if alias.lower() == "alias":
                continue                                   # header
            norm, canon_norm = _norm_name(alias), _norm_name(canon)
            if not norm or not canon_norm or not _alias_ok(norm):
                continue
            if canonical is not None:
                if canon_norm not in canonical:
                    continue                               # unknown employer: never introduce one
                canon = canonical[canon_norm]              # use the reference list's own label
                if norm in canonical:
                    continue                               # already a canonical name: nothing to add
            if norm in claimed and claimed[norm] != canon:
                dropped.add(norm)                          # two employers claim it: ambiguous
                continue
            claimed[norm] = canon
    for norm in dropped:
        claimed.pop(norm, None)
    return sorted(claimed.items(), key=lambda kv: -len(kv[0]))


def employer_names(domains: dict[str, tuple[str, str]],
                   aliases_path: Path | str | None = EMPLOYER_ALIASES_FILE) -> list[tuple[str, str]]:
    """Distinctive employer names to match in the COMPANY_NAME field, longest first.

    Includes the offline-built alias table, so the same employer still matches when it is typed as
    a legal entity ("Goldman Sachs International"), spaced differently ("J P Morgan" normalises to
    different tokens than "JPMorgan"), or misspelled. Matching stays exact and deterministic; the
    aliases are simply more rows to compare against."""
    seen: dict[str, str] = {}
    for org, _cat in domains.values():
        norm = _norm_name(org)
        if norm and _distinctive(norm):
            seen.setdefault(norm, org)
    if aliases_path is not None:
        for norm, org in load_aliases(aliases_path, canonical=dict(seen)):
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
