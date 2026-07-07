"""Build the UK company-controllers reference table from free Companies House bulk data.

This keeps only the HIGH-PRECISION "eponymous company owner" subset: a person who owns or controls
75%+ of an ACTIVE UK company whose own SURNAME is a word in the company's name ("[Surname] Holdings
Ltd"). Controlling a company named after you is a near-pure wealth tell. Each kept controller is
graded into a tier (match / high / prime) by company size and industry, so the runtime signal can
weight a large or wealth-industry owner above a small generic one.

Two free Companies House bulk products are joined (offline — never a live per-name API):

  1. PSC snapshot            persons-with-significant-control-snapshot-<date>.zip  (NDJSON in a zip)
        gives: person name + name_elements.surname + company_number + natures_of_control
        https://download.companieshouse.gov.uk/en_pscdata.html
  2. Basic Company Data      BasicCompanyDataAsOneFile-<date>.zip                  (one big CSV)
        gives: CompanyNumber -> CompanyName, CompanyStatus, CompanyCategory (PLC?),
               Accounts.AccountCategory (size band), SICCode.SicText_1..4 (industry)
        https://download.companieshouse.gov.uk/en_output.html

Precision (all applied here at BUILD time so the runtime match stays a simple O(1) name lookup):
  - keep only individual PSCs with a 75-100% ownership/voting band (``--min-control`` 75 or 50)
  - drop common surnames (an eponymous "Smith Ltd" tells you little)
  - require the surname to be a word in the company name (the eponymous two-factor) UNLESS the
    company is BOTH large and a wealth industry (a strong-enough wealth fact to stand without it)
  - require the company to be ACTIVE and not a dormant / micro-entity shell (with one exception:
    an eponymous + wealth-SIC micro-entity — the quiet family investment vehicle — is kept at
    the dampened ``match`` tier)
  - tier by size (Medium/Full/Group/audited or PLC = large) and wealth-industry SIC; eponymy earns
    the top ``prime`` band, a non-eponymous large+wealth owner lands at ``high``

Stand-alone operator tool (NOT imported by the app or tests); standard library only.

Usage
-----
    python scripts/build_company_controllers.py \
        --psc persons-with-significant-control-snapshot-2026-06-01.zip \
        --companies BasicCompanyDataAsOneFile-2026-06-01.zip \
        [--min-control 75] [--replace]

By default rows are MERGED with the existing table (so a hand-added row survives); use --replace to
overwrite. --out defaults to the git-ignored local table the signal prefers, so real named
individuals never land in git.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import UK_COMPANY_CONTROLLERS_LOCAL_FILE  # noqa: E402

INDIVIDUAL_KIND = "individual-person-with-significant-control"

# Very common GB surnames — an eponymous "Smith Ltd" match tells you little, so drop these.
# (Kept in sync with scripts/build_charity_trustees.py.)
_COMMON_SURNAMES = {
    "SMITH", "JONES", "WILLIAMS", "BROWN", "TAYLOR", "DAVIES", "WILSON", "EVANS", "THOMAS",
    "ROBERTS", "JOHNSON", "LEWIS", "WALKER", "ROBINSON", "WOOD", "THOMPSON", "WHITE", "WATSON",
    "JACKSON", "WRIGHT", "GREEN", "HARRIS", "COOPER", "KING", "LEE", "MARTIN", "CLARKE", "JAMES",
    "MORGAN", "HUGHES", "EDWARDS", "HILL", "MOORE", "CLARK", "HARRISON", "SCOTT", "YOUNG", "MORRIS",
    "HALL", "WARD", "TURNER", "CARTER", "PHILLIPS", "MITCHELL", "PATEL", "ADAMS", "CAMPBELL",
    "ANDERSON", "ALLEN", "COOK", "BAILEY", "PARKER", "MILLER", "DAVIS", "MURPHY", "PRICE", "BELL",
    "BAKER", "GRIFFITHS", "KELLY", "SIMPSON", "MARSHALL", "COLLINS", "BENNETT", "COX", "RICHARDSON",
    "FOX", "GRAY", "ROSE", "CHAPMAN", "HUNT", "ROBERTSON", "SHAW", "REYNOLDS", "KNIGHT", "BARNES",
    "POWELL", "STEVENS", "PEARSON", "STEWART", "GRAHAM", "OWEN", "REID", "MURRAY", "PALMER", "HOLMES",
    "MASON", "GORDON", "HUNTER", "ELLIS", "GIBSON", "WELLS", "WEBB", "FISHER", "GEORGE", "DAY",
    "GRANT", "MILLS", "RILEY", "BURTON", "LLOYD", "BALL", "HARVEY", "OLIVER", "COLE", "BUTLER",
    "AHMED", "KHAN", "SINGH", "BEGUM", "ALI", "HUSSAIN",
}

# Generic words in a company name that are not a surname (so we do not treat them as an eponym).
_STOPWORDS = {
    "THE", "AND", "OF", "FOR", "A", "AN", "IN", "TO", "LIMITED", "LTD", "PLC", "LLP", "LP", "CIC",
    "HOLDINGS", "HOLDING", "GROUP", "COMPANY", "CO", "TRADING", "INVESTMENTS", "INVESTMENT",
    "PROPERTIES", "PROPERTY", "CAPITAL", "PARTNERS", "PARTNERSHIP", "ASSOCIATES", "ENTERPRISES",
    "VENTURES", "MANAGEMENT", "CONSULTING", "CONSULTANTS", "SERVICES", "SOLUTIONS", "INTERNATIONAL",
    "UK", "GB", "LONDON", "ENGLAND", "GLOBAL", "ESTATES", "ESTATE", "FAMILY", "AND", "TRUST",
}

# Accounts categories that indicate a materially LARGE company (turnover thresholds: small <=£10.2M,
# medium <=£36M, large/full above). Dormant / never-filed are shells we drop entirely. Micro-entity
# is USUALLY a shell too — except the quiet family wealth vehicle ("[Surname] Investments Ltd"
# filing micro accounts on purpose), so an eponymous + wealth-SIC micro is kept, dampened to
# the 'match' tier (micro accounts tell us nothing about scale).
_LARGE_ACCOUNTS = {"MEDIUM", "FULL", "GROUP"}     # substring test also catches "…AUDITED…"
_ALWAYS_SHELL = {"DORMANT", "NO ACCOUNTS FILED"}

# SIC (Standard Industrial Classification) codes -> the wealth-industry label shown in the reason.
# These are the sectors that read as HNW wealth / creative-professional vehicles.
_WEALTH_SIC = {
    # Real estate
    "68100": "real estate", "68209": "real estate", "68310": "real estate",
    "68320": "real estate", "68201": "real estate", "68202": "real estate",
    # Investment / holding / fund management — the classic family-wealth vehicles
    "64209": "holding", "64205": "holding", "70100": "holding",
    "64303": "investment", "64304": "investment", "64305": "investment", "64306": "investment",
    "64999": "investment", "66300": "investment", "64301": "investment", "64302": "investment",
    # Architecture
    "71111": "architecture",
    # Design services
    "74100": "design", "74201": "design", "74202": "design", "74203": "design",
    # Art / creative
    "90030": "art", "47789": "art", "91020": "art",
}


def _title(text: str) -> str:
    """Best-effort human casing for an ALL-CAPS register name."""
    return " ".join(w.capitalize() for w in text.split())


def _norm_tokens(text: str) -> list[str]:
    return [t for t in re.sub(r"[^A-Z0-9]+", " ", (text or "").upper()).split() if t]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", (text or "").upper())).strip()


def _person_from_record(rec: dict) -> tuple[str, str, str] | None:
    """Return (display_name, surname, company_number) for a qualifying individual PSC, else None.

    Qualifies only when kind is an individual PSC AND natures_of_control includes a high band.
    """
    data = rec.get("data") or rec
    if data.get("kind") != INDIVIDUAL_KIND:
        return None
    company_number = str(rec.get("company_number") or data.get("company_number") or "").strip()
    if not company_number:
        return None
    natures = data.get("natures_of_control") or []
    if not any(band in str(n) for band in _HIGH_BANDS for n in natures):
        return None
    elements = data.get("name_elements") or {}
    forename = (elements.get("forename") or "").strip()
    surname = (elements.get("surname") or "").strip()
    if forename and surname:
        full = f"{forename} {surname}"
    else:
        full = (data.get("name") or "").strip()
        surname = _norm_tokens(full)[-1] if _norm_tokens(full) else ""
    full = full.strip()
    if not full or not surname:
        return None
    display = _title(full) if full.isupper() else full
    return display, _normalize(surname), company_number


# Set by main() from --min-control; natures_of_control substrings accepted as "high" control.
# 75 keeps only the top band; 50 also admits the 50-75% band.
_HIGH_BANDS = {"75-to-100-percent"}


def _iter_psc(paths: list[Path]):
    """Yield decoded JSON PSC records from snapshot file(s) (.zip of NDJSON, or a .txt of NDJSON)."""
    for path in paths:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for member in zf.namelist():
                    if member.endswith("/"):
                        continue
                    with zf.open(member) as raw:
                        for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                yield json.loads(line)
                            except json.JSONDecodeError:
                                continue
        else:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


def _open_company_csv(path: Path):
    """Yield csv.DictReader rows from Basic Company Data (.zip of one CSV, or a plain .csv)."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            member = next((m for m in zf.namelist() if m.lower().endswith(".csv")), None)
            if member is None:
                raise SystemExit(f"No CSV inside {path}")
            with zf.open(member) as raw:
                yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", errors="replace"))
    else:
        with path.open(encoding="utf-8", errors="replace", newline="") as fh:
            yield from csv.DictReader(fh)


def _col(row: dict, *names: str) -> str:
    """Fetch a Basic Company Data column tolerant of the leading spaces in its header names."""
    for n in names:
        for key in (n, f" {n}", n.strip()):
            if key in row and row[key] not in (None, ""):
                return str(row[key]).strip()
    # last resort: match ignoring surrounding whitespace in the header
    for k, v in row.items():
        if k and k.strip() in names and v not in (None, ""):
            return str(v).strip()
    return ""


def _classify(account_cat: str, company_cat: str, sic_texts: list[str]):
    """Return (is_large, is_wealth, industry_label). industry '' when not a wealth-industry SIC."""
    ac = account_cat.upper()
    is_large = (any(w in ac for w in _LARGE_ACCOUNTS) or "AUDITED" in ac
                or "PUBLIC LIMITED" in company_cat.upper() or company_cat.upper() == "PLC")
    industry = ""
    for text in sic_texts:
        code = (re.match(r"\s*(\d{4,5})", text or "") or [None, None])[1]
        if code and code in _WEALTH_SIC:
            industry = _WEALTH_SIC[code]
            break
    return is_large, bool(industry), industry


def _tier(eponymous: bool, is_large: bool, is_wealth: bool) -> tuple[bool, str]:
    """Decide whether to keep a controller and at which tier.

    Keep when the surname is in the company name (eponymous) OR the company is BOTH large and a
    wealth industry — a strong-enough wealth fact to stand without the name match. Eponymy earns
    the top ``prime`` band; a non-eponymous large+wealth owner lands one notch down at ``high``.
    """
    if is_large and is_wealth:
        return True, ("prime" if eponymous else "high")
    if eponymous:
        return True, ("high" if (is_large or is_wealth) else "match")
    return False, ""


def _is_shell(account_cat: str) -> bool:
    ac = account_cat.upper()
    return any(s in ac for s in _ALWAYS_SHELL)


def _is_micro(account_cat: str) -> bool:
    return "MICRO" in account_cat.upper()


def build(psc: list[Path], companies: Path, out: Path, replace: bool, limit: int) -> None:
    # Pass 1: stream PSC, collect eligible eponymous candidates keyed by company number.
    # candidates[company_number] = list of (display_name, surname)
    candidates: dict[str, list[tuple[str, str]]] = {}
    scanned = eligible = 0
    for rec in _iter_psc(psc):
        scanned += 1
        if scanned % 1_000_000 == 0:
            print(f"  … {scanned:,} PSC records, {len(candidates):,} companies with a candidate",
                  file=sys.stderr)
        got = _person_from_record(rec)
        if not got:
            continue
        display, surname, company_number = got
        if not surname or surname in _COMMON_SURNAMES:
            continue
        candidates.setdefault(company_number, []).append((display, surname))
        eligible += 1
    print(f"PSC scanned: {scanned:,}  high-control eligible people: {eligible:,}  "
          f"companies to check: {len(candidates):,}", file=sys.stderr)

    # Pass 2: stream Basic Company Data; for each candidate company, apply the eponymous +
    # active + non-shell test and tier by size/industry. When a person controls several kept
    # companies, their HIGHEST tier wins (not whichever company happens to stream first).
    tier_rank = {"match": 0, "high": 1, "prime": 2}
    rows: dict[str, tuple[str, str, str, str]] = {}   # norm name -> (name, tier, company, industry)
    kept = 0
    for row in _open_company_csv(companies):
        number = _col(row, "CompanyNumber", "company_number")
        if number not in candidates:
            continue
        status = _col(row, "CompanyStatus")
        if status and status.lower() != "active":
            continue
        account_cat = _col(row, "Accounts.AccountCategory", "AccountCategory")
        if _is_shell(account_cat):
            continue
        name = _col(row, "CompanyName", "company_name")
        if not name:
            continue
        company_cat = _col(row, "CompanyCategory")
        sic_texts = [_col(row, f"SICCode.SicText_{i}") for i in range(1, 5)]
        pool = set(_norm_tokens(name)) - _STOPWORDS
        is_large, is_wealth, industry = _classify(account_cat, company_cat, sic_texts)
        company_display = _title(name) if name.isupper() else name
        for display, surname in candidates[number]:
            eponymous = surname in pool
            if _is_micro(account_cat):
                # Micro-entity: a shell UNLESS it reads as a quiet family wealth vehicle —
                # eponymous AND a wealth-industry SIC — kept at the dampened 'match' tier.
                if not (eponymous and is_wealth):
                    continue
                keep, tier = True, "match"
            else:
                keep, tier = _tier(eponymous, is_large, is_wealth)
            if not keep:
                continue
            norm = _normalize(display)
            if not norm:
                continue
            prev = rows.get(norm)
            if prev is None:
                rows[norm] = (display, tier, company_display, industry)
                kept += 1
            elif tier_rank.get(tier, 0) > tier_rank.get(prev[1], 0):
                rows[norm] = (display, tier, company_display, industry)
        if limit and kept >= limit:
            break

    # Merge with the existing table unless --replace, then write name,tier,company,industry.
    existing: dict[str, tuple[str, str, str, str]] = {}
    if not replace and out.exists():
        with out.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row or row[0].startswith("#") or row[0].strip().lower() == "name":
                    continue
                nm = row[0].strip()
                norm = _normalize(nm)
                existing.setdefault(norm, (
                    nm,
                    row[1].strip() if len(row) > 1 else "match",
                    row[2].strip() if len(row) > 2 else "",
                    row[3].strip() if len(row) > 3 else "",
                ))
    merged = {**existing, **rows}

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        fh.write("# UK company controllers (75%+ owners: eponymous, or large wealth-industry) — Companies House, OGL v3.0.\n")
        fh.write("# Generated by scripts/build_company_controllers.py. Columns: name,tier,company,industry\n")
        w.writerow(["name", "tier", "company", "industry"])
        for nm, tier, company, industry in sorted(merged.values(), key=lambda x: x[0].lower()):
            w.writerow([nm, tier, company, industry])

    tiers = {}
    for _, tier, _, _ in merged.values():
        tiers[tier] = tiers.get(tier, 0) + 1
    print(f"eponymous owners kept: {kept:,}  unique written: {len(merged):,}  "
          f"tiers: {tiers}  -> {out}", file=sys.stderr)


def main() -> None:
    global _HIGH_BANDS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--psc", nargs="+", required=True, type=Path,
                    help="PSC snapshot file(s): .zip or NDJSON .txt")
    ap.add_argument("--companies", required=True, type=Path,
                    help="Basic Company Data (BasicCompanyDataAsOneFile .zip or a .csv)")
    ap.add_argument("--min-control", type=int, choices=(50, 75), default=75,
                    help="minimum ownership/voting band to keep (default 75)")
    ap.add_argument("--replace", action="store_true", help="overwrite instead of merging the seed")
    ap.add_argument("--limit", type=int, default=0, help="stop after N kept owners (0 = all; testing)")
    ap.add_argument("--out", type=Path, default=Path(UK_COMPANY_CONTROLLERS_LOCAL_FILE),
                    help="output CSV (default: the git-ignored local table the signal prefers)")
    a = ap.parse_args()
    _HIGH_BANDS = ({"75-to-100-percent"} if a.min_control == 75
                   else {"75-to-100-percent", "50-to-75-percent"})
    for p in (*a.psc, a.companies):
        if not p.exists():
            ap.error(f"file not found: {p}")
    build(list(a.psc), a.companies, a.out, a.replace, a.limit)


if __name__ == "__main__":
    main()
