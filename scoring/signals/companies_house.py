"""Companies House control signal (UK, from the open PSC + Basic Company Data).

Flags customers whose name matches the compact, HIGH-PRECISION subset Halia keeps from the
Companies House register: people who own or control 75%+ of an active UK company that is either
**named after them** (their surname is in the company name, "[Surname] Holdings Ltd") OR is **both
large and in a wealth industry** (a strong-enough wealth fact to stand without the name match).
Controlling such a company is a near-pure wealth / work FACT, so this signal is ON by default; it is
not an origin proxy.

The match is graded by how telling the company is (built into the table at BUILD time):
  - ``match`` : a plain eponymous, smaller, generic-industry company            (base weight)
  - ``high``  : eponymous AND (large OR a wealth industry), OR a non-eponymous company that is
                large AND a wealth industry (large = Full/Medium/Group accounts or a PLC;
                wealth = real estate, investment/holding, architecture, design, art SIC)
  - ``prime`` : eponymous AND large AND a wealth industry

NAMESAKE CERTAINTY. When more than one distinct person on the register shares a full name (compared
by public birth month/year at build time), a bare name match can never be certain. Those rows carry
the postcode DISTRICT of the person's PSC service address, and the signal only fires when the
customer's billing or shipping postcode lands in that district — name AND address agreeing across
two independent sources. Unique names match on name alone, as before.

Like `charity_trustee`, this is a match against a public statutory register, so it stays a
deliberately CORROBORATION-ONLY signal (in SUPPORTING_SIGNALS in the combiner and in the `name`
group): it never surfaces a customer on its own, it only adds weight when a stronger signal has also
fired. The precision lives in the table (eponymous + 75% control + active + size/SIC + the
ambiguity/address gate), not in promoting it to a core signal.

The reference table (reference_data/companies/uk_company_controllers.csv) ships INERT (fictional
examples only). Regenerate it to real coverage from the free Companies House PSC snapshot joined to
Basic Company Data with scripts/build_company_controllers.py. Naming private controllers in the repo
is exactly the sensitivity Halia is careful about, so real people only enter the table on the
operator's own machine (the git-ignored .local.csv, preferred when present).

Data: Companies House, Open Government Licence v3.0 (attribution).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

from config import UK_COMPANY_CONTROLLERS_FILE, UK_COMPANY_CONTROLLERS_LOCAL_FILE
from scoring.signals.property_value import _outcode

FLAG_COL = "companies_house"
REASON_COL = "companies_house_reason"
TYPE_COL = "companies_house_tier"       # per-row tier; the combiner maps it -> weight

_ZIP_COLS = ["LATEST_BILLING_ZIP", "LATEST_SHIPPING_ZIP"]
_TIER_RANK = {"prime": 2, "high": 1, "match": 0}


def _default_path() -> Path:
    """Prefer the operator's git-ignored real table when it exists, else the committed seed."""
    local = Path(UK_COMPANY_CONTROLLERS_LOCAL_FILE)
    return local if local.exists() else Path(UK_COMPANY_CONTROLLERS_FILE)


def _normalize(value: object) -> str:
    """Upper-case, strip non-alphanumerics to single spaces (same shape as charity_trustee)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    t = re.sub(r"[^A-Z0-9]+", " ", str(value).upper())
    return re.sub(r"\s+", " ", t).strip()


def _reason(name: str, company: str, industry: str) -> str:
    """Human reason naming the company and (when known) what its SIC code indicates."""
    if company and industry:
        article = "an" if industry[:1].lower() in "aeiou" else "a"
        return f"{name} — controls {company}, {article} {industry} company (Companies House)"
    if company:
        return f"{name} — controls {company} (Companies House)"
    return f"{name} — controls a UK company (Companies House)"


def load_controllers(path: Path | str | None = None) -> dict[str, list[tuple[str, str, str]]]:
    """Read {normalized_name: [(display_reason, tier, required_district), ...]}.

    CSV columns: name[, tier[, company[, industry[, district]]]]. Blank/comment/header rows are
    skipped. ``tier`` is one of match/high/prime (defaults to "match"); ``company``/``industry``
    name the company (and what its SIC indicates) in the human reason. ``district``, when set,
    is the person's PSC service-address postcode district: the entry only matches a customer
    whose billing/shipping postcode is in that district (the ambiguous-name gate). A name can
    have several entries (namesakes at different addresses); they are kept strongest-tier first.
    A dict with an exact normalized-name key keeps matching O(1) on large regenerated tables.
    """
    path = Path(path) if path is not None else _default_path()
    if not path.exists():
        raise FileNotFoundError(f"Company-controllers reference not found: {path}")
    table: dict[str, list[tuple[str, str, str]]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            name = row[0].strip()
            if not name or name.startswith("#") or name.lower() == "name":
                continue
            norm = _normalize(name)
            if not norm:
                continue
            tier = row[1].strip().lower() if len(row) > 1 and row[1].strip() else "match"
            company = row[2].strip() if len(row) > 2 and row[2].strip() else ""
            industry = row[3].strip() if len(row) > 3 and row[3].strip() else ""
            district = row[4].strip().upper() if len(row) > 4 and row[4].strip() else ""
            table.setdefault(norm, []).append((_reason(name, company, industry), tier, district))
    for entries in table.values():
        entries.sort(key=lambda e: _TIER_RANK.get(e[1], 0), reverse=True)
    return table


def match_name(name: object, table: dict[str, list[tuple[str, str, str]]],
               districts: frozenset[str] | set[str] = frozenset(),
               ) -> tuple[bool, str | None, str | None]:
    """Exact (normalized) match of a customer name against the controller table.

    ``districts`` is the customer's billing/shipping postcode district set. An entry with a
    required district only matches when the customer's postcode agrees (the namesake gate); an
    entry without one matches on name alone. The strongest eligible tier wins.
    """
    norm = _normalize(name)
    if not norm:
        return False, None, None
    for reason, tier, need in table.get(norm, ()):    # strongest tier first
        if not need:
            return True, reason, tier
        if need in districts:
            # comma, not "; " — "; " is the dashboard's reason separator, so a semicolon here
            # would leak this corroboration note out as its own broken filter chip.
            return True, f"{reason[:-1]}, register address matches)", tier
    return False, None, None


def _row_districts(row: pd.Series, zip_cols: list[str]) -> frozenset[str]:
    """The customer's billing/shipping postcode districts, for the namesake gate."""
    out = set()
    for col in zip_cols:
        d = _outcode(row.get(col))
        if d:
            out.add(d)
    return frozenset(out)


def flag_companies_house(df: pd.DataFrame, table=None, name_col: str = "Name") -> pd.DataFrame:
    """Add companies_house flag + reason + tier columns to a copy of ``df``."""
    if table is None:
        table = load_controllers()
    out = df.copy()
    if name_col not in out.columns:
        out[FLAG_COL] = False
        out[REASON_COL] = None
        out[TYPE_COL] = None
        return out
    zip_cols = [c for c in _ZIP_COLS if c in out.columns]
    results = [
        match_name(row[name_col], table, _row_districts(row, zip_cols))
        for _, row in out.iterrows()
    ]
    out[FLAG_COL] = [hit for hit, _, _ in results]
    out[REASON_COL] = [reason for _, reason, _ in results]
    out[TYPE_COL] = [tier for _, _, tier in results]
    return out
