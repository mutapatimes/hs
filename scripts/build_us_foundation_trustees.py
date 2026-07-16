"""Build the US eponymous-foundation-trustee reference table from IRS Form 990-PF filings.

Every US private foundation files a Form 990-PF listing its officers, directors and trustees. The
IRS republishes these as machine-readable XML (public domain). This keeps only the HIGH-PRECISION
eponymous subset: a trustee whose own SURNAME is a word in the foundation's name ("The [Surname]
Family Foundation"). A family foundation named after you, with you on its board, is a near-pure
wealth tell. The US analog to build_charity_trustees.py (which does the same for the UK).

Stand-alone operator tool (NOT imported by the app or tests). Standard library only.

Download the data first (free, public domain):
    IRS 990 filings are published as XML. Two common sources:
      * IRS bulk: https://www.irs.gov/charities-non-profits/form-990-series-downloads
      * AWS mirror: the s3://irs-form-990 bucket (index files list every filing's XML URL).
    Fetch a year's 990-PF XML files into a folder (each filing is one .xml). This script scans a
    folder (recursively) for .xml files; non-990-PF returns are skipped automatically.

Usage
-----
    python scripts/build_us_foundation_trustees.py --dir ~/Downloads/irs-990pf-2024
    python scripts/build_us_foundation_trustees.py --dir <folder> [<folder> ...] --replace

Precision (applied here at BUILD time so the runtime match stays a simple O(1) name lookup):
  - keep only 990-PF returns (private foundations), read the foundation name from the filer header
  - keep only officers/directors/trustees who are PEOPLE (drop corporate co-trustees like banks)
  - require the person's SURNAME to be a whole word in the foundation name (the eponymous filter)
  - drop very common surnames (an eponymous "Smith Foundation" tells you little)
  - collapse to one row per person; the display name is title-cased
  - MERGE with the existing table by default (a hand-added row survives); --replace overwrites.
    --out defaults to the git-ignored local table, so real named individuals never land in git.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import US_FOUNDATION_TRUSTEES_LOCAL_FILE  # noqa: E402

_COMMON_SURNAMES = {
    "SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ",
    "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "ANDERSON", "THOMAS", "TAYLOR", "MOORE",
    "JACKSON", "MARTIN", "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS", "SANCHEZ", "CLARK", "RAMIREZ",
    "LEWIS", "ROBINSON", "WALKER", "YOUNG", "ALLEN", "KING", "WRIGHT", "SCOTT", "TORRES", "NGUYEN",
    "HILL", "GREEN", "ADAMS", "NELSON", "BAKER", "HALL", "CAMPBELL", "MITCHELL", "COOK", "MURPHY",
}
# Foundation-name words that are NOT surnames — never treat these as the eponymous token.
_STOP = {"THE", "FAMILY", "FOUNDATION", "CHARITABLE", "TRUST", "FUND", "FUNDS", "INC", "AND", "OF",
         "FOR", "A", "MEMORIAL", "COMMUNITY", "CHARITIES", "GIVING", "REVOCABLE", "IRREVOCABLE",
         "LIVING", "ENDOWMENT", "SCHOLARSHIP", "OPERATING", "CORPORATION", "CO", "LLC", "LP",
         "PRIVATE", "PUBLIC", "TRUSTEES", "TRUSTEE", "USA", "AMERICA", "AMERICAN", "INTERNATIONAL"}
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "PHD", "ESQ", "DDS", "CPA"}
_ENTITY_HINTS = {"BANK", "TRUST", "COMPANY", "CO", "NA", "NATIONAL", "LLC", "LP", "INC", "CORP",
                 "FARGO", "MELLON", "FIDUCIARY", "TRUSTEES", "CORPORATION", "ASSOCIATION"}


def _local(tag: str) -> str:
    """Strip an XML namespace: '{http://www.irs.gov/efile}PersonNm' -> 'PersonNm'."""
    return tag.rsplit("}", 1)[-1]


def _first_text(elem, *localnames: str) -> str:
    """First descendant whose local tag is one of localnames, its stripped text (else '')."""
    wanted = set(localnames)
    for node in elem.iter():
        if _local(node.tag) in wanted and (node.text or "").strip():
            return node.text.strip()
    return ""


def _words(text: str) -> set[str]:
    return {w for w in "".join(c if c.isalpha() else " " for c in text.upper()).split() if w}


def _name_parts(raw: str) -> tuple[str, str] | None:
    """(display_name, SURNAME) from a 990 person name; None if it looks like an entity."""
    raw = " ".join(raw.split())
    up = raw.upper()
    toks_all = up.replace(",", " ").split()
    if any(h in toks_all for h in _ENTITY_HINTS):
        return None                                       # a corporate co-trustee (bank etc.)
    if "," in raw:                                        # "Last, First Middle"
        surname = raw.split(",", 1)[0].strip()
        rest = raw.split(",", 1)[1].strip()
        display = f"{rest} {surname}".strip()
    else:                                                 # "First Middle Last [Suffix]"
        toks = [t for t in raw.split() if t.upper().strip(".") not in _SUFFIXES]
        if len(toks) < 2:
            return None
        surname = toks[-1]
        display = " ".join(toks)
    surname_u = "".join(c for c in surname.upper() if c.isalpha())
    if len(surname_u) < 3:
        return None
    return " ".join(w.capitalize() for w in display.split()), surname_u


def _people(return_elem):
    """Yield officer/director/trustee person names from a 990-PF return element."""
    for node in return_elem.iter():
        lt = _local(node.tag)
        # 990-PF officer/trustee groups across schema years: OfficerDirTrstKeyEmplGrp,
        # Form990PartVIISectionAGrp, OfficerDirectorTrusteeEmplGrp, etc. Match broadly.
        if ("OfficerDir" in lt or "TrstKey" in lt or "TrusteeOr" in lt
                or "OffcrDirTrusteesOrKeyEmpl" in lt):
            nm = _first_text(node, "PersonNm", "PersonNemeControlTxt", "BusinessNameLine1Txt")
            if nm:
                yield nm


def _foundation_name(root) -> str:
    """The filer/foundation business name from the return header."""
    for node in root.iter():
        if _local(node.tag) in ("Filer", "BusinessOfficerGrp"):
            nm = _first_text(node, "BusinessNameLine1Txt", "BusinessNameLine1")
            if nm:
                return " ".join(nm.split())
    return _first_text(root, "BusinessNameLine1Txt", "BusinessNameLine1")


def process_file(path: Path) -> list[tuple[str, str]]:
    """One 990-PF XML file -> [(display_name, foundation_name)] for eponymous trustees."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []
    is_pf = any(_local(n.tag) in ("IRS990PF", "ReturnTypeCd") and
                ("IRS990PF" == _local(n.tag) or (n.text or "").strip() == "990PF")
                for n in root.iter())
    if not is_pf:
        return []
    return_elem = next((n for n in root.iter() if _local(n.tag) == "ReturnData"), root)
    fname = _foundation_name(root)
    if not fname:
        return []
    fwords = _words(fname)
    out = []
    for raw in _people(return_elem):
        parsed = _name_parts(raw)
        if not parsed:
            continue
        display, surname = parsed
        if surname in _COMMON_SURNAMES or surname in _STOP:
            continue
        if surname in fwords:                             # the eponymous two-factor
            out.append((display, fname.title()))
    return out


def build(dirs: list[Path]) -> dict[str, tuple[str, str]]:
    """Scan folders of 990-PF XML -> {normalized_name: (display_name, foundation_name)}."""
    table: dict[str, tuple[str, str]] = {}
    files = [p for d in dirs for p in Path(d).rglob("*.xml")]
    for i, path in enumerate(files):
        for display, foundation in process_file(path):
            key = "".join(c if c.isalnum() else " " for c in display.upper()).split()
            key = " ".join(key)
            table.setdefault(key, (display, foundation))
        if (i + 1) % 5000 == 0:
            print(f"  ...scanned {i + 1}/{len(files)} filings, {len(table)} eponymous trustees")
    return table


def load_existing(path: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return out
    for row in csv.reader(path.open(newline="", encoding="utf-8")):
        if not row or not row[0].strip() or row[0].startswith("#") or row[0].lower() == "name":
            continue
        key = " ".join("".join(c if c.isalnum() else " " for c in row[0].upper()).split())
        out[key] = (row[0].strip(), row[1].strip() if len(row) > 1 else "")
    return out


def write_table(path: Path, rows: dict[str, tuple[str, str]]) -> None:
    lines = [
        "name,foundation",
        "# US eponymous private-foundation trustees (IRS Form 990-PF). Regenerate with",
        "# scripts/build_us_foundation_trustees.py. Lines starting with # are ignored.",
    ]
    for name, foundation in sorted(rows.values(), key=lambda v: v[0].lower()):
        lines.append(f"{name},{foundation.replace(',', ' ').strip()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the US foundation-trustee table from IRS 990-PF XML.")
    ap.add_argument("--dir", type=Path, nargs="+", required=True, help="Folder(s) of 990-PF XML files")
    ap.add_argument("--out", type=Path, default=US_FOUNDATION_TRUSTEES_LOCAL_FILE)
    ap.add_argument("--replace", action="store_true", help="Overwrite instead of merging.")
    args = ap.parse_args()

    merged = {} if args.replace else load_existing(args.out)
    merged.update(build(args.dir))
    write_table(args.out, merged)
    print(f"Wrote {len(merged)} eponymous foundation trustees to {args.out}.")


if __name__ == "__main__":
    main()
