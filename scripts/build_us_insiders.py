"""Build the US corporate-insider reference table from the free SEC Insider Transactions Data Sets.

Every director, officer, or 10%+ owner of a US public company files a Form 3/4/5 with the SEC. The
SEC republishes those filings as quarterly, tab-delimited data sets (public domain, no login). This
script reads a quarter's SUBMISSION + REPORTINGOWNER tables, keeps the reporting owners who are
directors / officers / 10% owners, grades each into a role tier, and writes
reference_data/companies/us_insiders.csv, which the ``us_insider`` signal reads. The US analog to
build_company_controllers.py (which does the same for the UK from Companies House).

Stand-alone operator tool (NOT imported by the app or tests). Standard library only.

Download the data first (free, no login):
    SEC -> https://www.sec.gov/dera/data/insider-transactions-data-sets
    Grab one or more quarterly zips, e.g. 2026q1_form345.zip, and unzip them. Each unzips to a
    folder of .tsv files; this script needs SUBMISSION.tsv and REPORTINGOWNER.tsv from each.

Usage
-----
    python scripts/build_us_insiders.py --dir ~/Downloads/2026q1_form345 [~/Downloads/2025q4_form345 ...]
    python scripts/build_us_insiders.py --dir <folder> --min-count 2 --replace

Precision (applied here at BUILD time so the runtime match stays a simple O(1) key lookup):
  - keep only reporting owners flagged as Director, Officer, or 10% owner (drop everything else)
  - tier: a 10% owner -> ``owner`` (a large equity stake); a plain director/officer -> ``insider``
  - collapse to one row per person (order-independent FIRST+LAST key), keeping the strongest tier
    and a representative company; the display name is re-ordered surname-last for readability
  - drop keys whose first+last pair is very common (``--drop-common``, from a small stoplist) — a
    "John Smith" match tells you nothing; the signal is corroboration-only anyway
  - by default MERGE with the existing table (a hand-added row survives); --replace overwrites.
    --out defaults to the git-ignored local table, so real named individuals never land in git.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # make repo-root `config` importable
from config import US_INSIDERS_LOCAL_FILE  # noqa: E402

# A tiny stoplist of very common US surname/forename pairs is pointless; instead we drop by the
# most common SURNAMES, since a match on a common surname + any forename carries little signal.
_COMMON_SURNAMES = {
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ",
    "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "ANDERSON", "THOMAS", "TAYLOR", "MOORE",
    "JACKSON", "MARTIN", "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS", "SANCHEZ", "CLARK", "RAMIREZ",
    "LEWIS", "ROBINSON", "WALKER", "YOUNG", "ALLEN", "KING", "WRIGHT", "SCOTT", "TORRES", "NGUYEN",
    "HILL", "FLORES", "GREEN", "ADAMS", "NELSON", "BAKER", "HALL", "RIVERA", "CAMPBELL", "MITCHELL",
}
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "PHD", "ESQ"}


def _tokens(value: str) -> list[str]:
    raw = "".join(ch if (ch.isalpha() or ch == " ") else " " for ch in str(value or "").upper())
    toks = [t for t in raw.split() if t]
    while len(toks) > 2 and toks[-1] in _SUFFIXES:
        toks.pop()
    return toks


def _key(value: str) -> str | None:
    toks = _tokens(value)
    if len(toks) < 2:
        return None
    return " ".join(sorted((toks[0], toks[-1])))


def _display(value: str) -> str:
    """SEC stores names surname-first ("Musk Elon"); re-order to "Elon Musk" for readability."""
    toks = [t for t in str(value or "").split() if t]
    suffix = toks.pop() if len(toks) > 2 and toks[-1].upper().strip(".") in _SUFFIXES else ""
    if len(toks) >= 2:
        toks = toks[1:] + [toks[0]]                        # move surname (first token) to the end
    if suffix:
        toks.append(suffix)
    return " ".join(w.capitalize() for w in toks)


def _cell(row: dict, *names: str) -> str:
    """Case-insensitive column read (SEC has shipped both UPPER and CamelCase headers over time)."""
    lower = {k.lower(): v for k, v in row.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _tier(row: dict) -> str | None:
    """owner if a 10% holder; insider if a director/officer; None otherwise (drop)."""
    rel = _cell(row, "RPTOWNER_RELATIONSHIP", "RPTOWNERRELATIONSHIP").lower()
    is_ten = _cell(row, "ISTENPERCENTOWNER", "IS_TENPERCENTOWNER") in ("1", "true", "Y", "y") \
        or "10%" in rel or "tenpercent" in rel.replace(" ", "")
    is_dir = _cell(row, "ISDIRECTOR", "IS_DIRECTOR") in ("1", "true", "Y", "y") or "director" in rel
    is_off = _cell(row, "ISOFFICER", "IS_OFFICER") in ("1", "true", "Y", "y") or "officer" in rel
    if is_ten:
        return "owner"
    if is_dir or is_off:
        return "insider"
    return None


def _read_tsv(path: Path):
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        yield from csv.DictReader(fh, delimiter="\t")


def _find(folder: Path, stem: str) -> Path | None:
    for p in folder.iterdir():
        if p.is_file() and p.stem.lower() == stem.lower() and p.suffix.lower() == ".tsv":
            return p
    return None


def build_from_dir(folder: Path) -> dict[str, tuple[str, str, str]]:
    """One quarter folder -> {key: (display_name, tier, company)}, strongest tier per person."""
    sub_path, own_path = _find(folder, "SUBMISSION"), _find(folder, "REPORTINGOWNER")
    if not sub_path or not own_path:
        raise FileNotFoundError(f"{folder}: need both SUBMISSION.tsv and REPORTINGOWNER.tsv")
    issuer = {}
    for r in _read_tsv(sub_path):
        acc = _cell(r, "ACCESSION_NUMBER", "ACCESSIONNUMBER")
        if acc:
            issuer[acc] = _cell(r, "ISSUERNAME")
    out: dict[str, tuple[str, str, str]] = {}
    for r in _read_tsv(own_path):
        tier = _tier(r)
        if not tier:
            continue
        name = _cell(r, "RPTOWNERNAME", "RPTOWNER_NAME")
        key = _key(name)
        if not key:
            continue
        toks = _tokens(name)
        if toks and toks[0] in _COMMON_SURNAMES:          # SEC name is surname-first
            continue
        acc = _cell(r, "ACCESSION_NUMBER", "ACCESSIONNUMBER")
        company = issuer.get(acc, "")
        prev = out.get(key)
        rank = {"owner": 1, "insider": 0}
        if prev is None or rank[tier] > rank[prev[1]]:
            out[key] = (_display(name), tier, company)
        elif prev and not prev[2] and company:
            out[key] = (prev[0], prev[1], company)
    return out


def merge(dst: dict, src: dict) -> None:
    rank = {"owner": 1, "insider": 0}
    for k, v in src.items():
        prev = dst.get(k)
        if prev is None or rank[v[1]] > rank[prev[1]]:
            dst[k] = v


def load_existing(path: Path) -> dict[str, tuple[str, str, str]]:
    out: dict[str, tuple[str, str, str]] = {}
    if not path.exists():
        return out
    for row in csv.reader(path.open(newline="", encoding="utf-8")):
        if not row or not row[0].strip() or row[0].startswith("#") or row[0].lower() == "name":
            continue
        k = _key(row[0])
        if not k:
            continue
        tier = row[1].strip().lower() if len(row) > 1 and row[1].strip() in ("insider", "owner") else "insider"
        company = row[2].strip() if len(row) > 2 else ""
        out[k] = (row[0].strip(), tier, company)
    return out


def write_table(path: Path, rows: dict[str, tuple[str, str, str]]) -> None:
    lines = [
        "name,tier,company",
        "# US corporate insiders — SEC Forms 3/4/5 reporting owners. Regenerate with",
        "# scripts/build_us_insiders.py. Lines starting with # are ignored. tier: insider/owner.",
    ]
    for name, tier, company in sorted(rows.values(), key=lambda v: v[0].lower()):
        safe = company.replace(",", " ").strip()
        lines.append(f"{name},{tier},{safe}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the US insider reference table from SEC Form 3/4/5 data sets.")
    ap.add_argument("--dir", type=Path, nargs="+", required=True, help="Unzipped quarter folder(s) with SUBMISSION.tsv + REPORTINGOWNER.tsv")
    ap.add_argument("--out", type=Path, default=US_INSIDERS_LOCAL_FILE)
    ap.add_argument("--replace", action="store_true", help="Overwrite instead of merging with the existing table.")
    args = ap.parse_args()

    merged: dict[str, tuple[str, str, str]] = {} if args.replace else load_existing(args.out)
    for folder in args.dir:
        merge(merged, build_from_dir(folder))
    write_table(args.out, merged)
    owners = sum(1 for _, t, _ in merged.values() if t == "owner")
    print(f"Wrote {len(merged)} insiders to {args.out} ({owners} 10% owners, {len(merged) - owners} directors/officers).")


if __name__ == "__main__":
    main()
