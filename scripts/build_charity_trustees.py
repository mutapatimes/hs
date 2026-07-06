"""Build the UK charity-trustees reference from the Charity Commission daily data extract.

The Charity Commission for England & Wales publishes a free daily extract of the public register
(Open Government Licence v3.0). Two of its tables matter here:

  - charity          : organisation_number, charity_name, latest_income, status, postcode, ...
  - charity_trustee  : organisation_number, trustee_id, trustee_name

This script joins them and keeps only the HIGH-PRECISION eponymous-foundation subset: a trustee
whose own SURNAME appears as a word in their charity's name ("The <Surname> Foundation"). A common-
surname stoplist (and an optional income floor) dampen the noise. It writes name,charity rows to
reference_data/charities/uk_charity_trustees.csv, which scoring/signals/charity_trustee.py reads.

Stand-alone operator tool (NOT imported by the app or tests); standard library only.

Source (free): https://register-of-charities.charitycommission.gov.uk/register/full-register-download

Usage
-----
    python scripts/build_charity_trustees.py \
        --trustees publicextract.charity_trustee.json \
        --charities publicextract.charity.json \
        [--other-names publicextract.charity_other_names.json] \
        [--min-income 100000] [--replace]

Notes
-----
- The extract files are JSON. This reads both a top-level JSON array and newline-delimited JSON.
- Match is two-factor (surname in the charity name AND the person is its trustee), applied here at
  build time, so the runtime signal stays a simple O(1) exact-name lookup.
- By default rows are MERGED with the existing seed (so the fictional example survives; use
  --replace to overwrite). The seed ships inert on purpose: real private trustees only ever live
  in your local copy of this file.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import UK_CHARITY_TRUSTEES_FILE  # noqa: E402

# Very common GB surnames — an eponymous "Smith Foundation" match tells you little, so drop these.
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

# Generic words in charity names that are not a surname (so we do not treat them as an eponym).
_STOPWORDS = {
    "THE", "AND", "OF", "FOR", "A", "AN", "IN", "TO", "TRUST", "FOUNDATION", "CHARITABLE",
    "CHARITY", "FUND", "FAMILY", "MEMORIAL", "SETTLEMENT", "ENDOWMENT", "LEGACY", "LIMITED",
    "LTD", "CIO", "UK", "GB", "ENGLAND", "WALES", "BRITISH", "ROYAL", "SAINT", "ST", "GROUP",
}


def _norm_tokens(text: str) -> list[str]:
    return [t for t in re.sub(r"[^A-Z0-9]+", " ", (text or "").upper()).split() if t]


def _surname(trustee_name: str) -> str:
    """Best-effort surname: the last name token that is not an initial. Handles 'A B Windsor'
    and 'WINDSOR, Charles' (comma-led) forms found in the register."""
    name = (trustee_name or "").strip()
    if "," in name:                              # "SURNAME, Forename" convention
        toks = _norm_tokens(name.split(",", 1)[0])
        return toks[-1] if toks else ""
    toks = [t for t in _norm_tokens(name) if len(t) > 1]
    return toks[-1] if toks else ""


def _iter_records(path: Path):
    """Yield dict records from a Charity Commission extract file (JSON array or NDJSON)."""
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        head = fh.read(1)
        while head and head.isspace():
            head = fh.read(1)
        fh.seek(0)
        if head == "[":                          # a single JSON array
            for rec in json.load(fh):
                if isinstance(rec, dict):
                    yield rec
            return
        for line in fh:                          # newline-delimited JSON
            line = line.strip().rstrip(",")
            if not line or line in "[]":
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                yield rec


def _get(rec: dict, *keys, default=""):
    for k in keys:
        if k in rec and rec[k] not in (None, ""):
            return rec[k]
    return default


def build(trustees: Path, charities: Path, other_names: Path | None,
          min_income: float, out: Path, replace: bool) -> None:
    # 1) charity map: organisation_number -> (name, income). Keep names by their org number.
    names: dict[str, str] = {}
    incomes: dict[str, float] = {}
    for rec in _iter_records(charities):
        org = str(_get(rec, "organisation_number", "registered_charity_number"))
        nm = str(_get(rec, "charity_name", "name"))
        if not org or not nm:
            continue
        # keep only linked_charity_number 0 (the main charity) when present
        if str(_get(rec, "linked_charity_number", default="0")) not in ("0", ""):
            continue
        names[org] = nm
        try:
            incomes[org] = float(_get(rec, "latest_income", "latest_acc_fin_period_income", default=0) or 0)
        except (TypeError, ValueError):
            incomes[org] = 0.0

    # optional alternative names, folded into the same org's token pool
    alt: dict[str, list[str]] = {}
    if other_names and other_names.exists():
        for rec in _iter_records(other_names):
            org = str(_get(rec, "organisation_number"))
            nm = str(_get(rec, "charity_name", "name"))
            if org and nm:
                alt.setdefault(org, []).append(nm)

    # 2) stream trustees, keep the eponymous, dampened, income-gated subset
    rows: dict[str, tuple[str, str]] = {}     # normalized name -> (display name, charity)
    seen = kept = 0
    for rec in _iter_records(trustees):
        seen += 1
        org = str(_get(rec, "organisation_number"))
        person = str(_get(rec, "trustee_name", "name")).strip()
        charity = names.get(org)
        if not person or not charity:
            continue
        if min_income and incomes.get(org, 0.0) < min_income:
            continue
        surname = _surname(person)
        if not surname or surname in _COMMON_SURNAMES:
            continue
        pool = set(_norm_tokens(charity))
        for a in alt.get(org, []):
            pool.update(_norm_tokens(a))
        pool -= _STOPWORDS
        if surname not in pool:                # two-factor: surname must be in the charity name
            continue
        norm = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", person.upper())).strip()
        if norm:
            rows.setdefault(norm, (person, charity))
            kept += 1

    # 3) merge with the existing file unless --replace, then write name,charity
    existing: dict[str, tuple[str, str]] = {}
    if not replace and out.exists():
        with out.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row or row[0].startswith("#") or row[0].strip().lower() == "name":
                    continue
                nm = row[0].strip()
                norm = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", nm.upper())).strip()
                existing.setdefault(norm, (nm, row[1].strip() if len(row) > 1 else ""))
    merged = {**existing, **rows}

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        fh.write("# UK charity trustees (eponymous foundations) — Charity Commission, OGL v3.0.\n")
        fh.write("# Generated by scripts/build_charity_trustees.py. Columns: name,charity\n")
        w.writerow(["name", "charity"])
        for nm, charity in sorted(merged.values(), key=lambda x: x[0].lower()):
            w.writerow([nm, charity])

    print(f"trustees scanned: {seen:,}  eponymous kept: {kept:,}  "
          f"unique written: {len(merged):,}  -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the UK charity-trustees reference table.")
    ap.add_argument("--trustees", required=True, type=Path, help="charity_trustee extract (JSON)")
    ap.add_argument("--charities", required=True, type=Path, help="charity extract (JSON)")
    ap.add_argument("--other-names", type=Path, default=None, help="charity_other_names extract (JSON)")
    ap.add_argument("--min-income", type=float, default=0.0,
                    help="only keep charities with latest income >= this (GBP). 0 = no floor.")
    ap.add_argument("--replace", action="store_true", help="overwrite instead of merging the seed")
    ap.add_argument("--out", type=Path, default=Path(UK_CHARITY_TRUSTEES_FILE))
    a = ap.parse_args()
    for p in (a.trustees, a.charities):
        if not p.exists():
            ap.error(f"file not found: {p}")
    build(a.trustees, a.charities, a.other_names, a.min_income, a.out, a.replace)


if __name__ == "__main__":
    main()
