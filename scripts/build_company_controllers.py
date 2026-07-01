"""Build the UK company-controllers reference table from Companies House PSC data.

Companies House publishes the "People with Significant Control (PSC) snapshot": every
person who owns or controls a UK company, free and open, as a large newline-delimited
JSON file (one record per line) distributed in a set of zips. This script reads that
snapshot, extracts the names of INDIVIDUAL persons of significant control, dedupes them,
and writes reference_data/companies/uk_company_controllers.csv, which the
companies_house signal reads.

It is a stand-alone operator tool (NOT imported by the app or the tests). It uses only
the standard library so it runs anywhere.

Source (free): https://download.companieshouse.gov.uk/en_pscdata.html

Usage
-----
    # Use already-downloaded snapshot file(s) — the reliable route (recommended):
    python scripts/build_company_controllers.py --files persons-with-significant-control-snapshot-2026-06-01.zip

    # Or point at the extracted .txt (newline-delimited JSON):
    python scripts/build_company_controllers.py --files psc-snapshot.txt

    # Attempt to download a dated snapshot automatically (URL changes each release):
    python scripts/build_company_controllers.py --date 2026-06-01

Notes
-----
- Snapshot files are large (~2-3 GB extracted). The script STREAMS line by line; it never
  holds the whole file in memory — only the set of unique names seen.
- Only ``kind == individual-person-with-significant-control`` records are kept (companies
  and legal-entity controllers are skipped — we match on a person's name).
- By default the table is MERGED with any existing rows (so the curated seed and any
  hand-added Scotland/NI or non-register entries survive). Use --replace to overwrite.
- Matching in the signal is exact-normalized-name, and the tell is corroboration-only, so
  the value is coverage: more names caught, never a sole basis.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import UK_COMPANY_CONTROLLERS_FILE  # noqa: E402

INDIVIDUAL_KIND = "individual-person-with-significant-control"
BASE_URL = "https://download.companieshouse.gov.uk"
ROLE = "PSC"


def _title(text: str) -> str:
    """Best-effort human casing for an ALL-CAPS register name."""
    return " ".join(w.capitalize() for w in text.split())


def _name_from_record(rec: dict) -> str | None:
    """Pull a person's full name from one PSC JSON record, or None if not an individual."""
    data = rec.get("data") or rec
    if data.get("kind") != INDIVIDUAL_KIND:
        return None
    elements = data.get("name_elements") or {}
    forename = (elements.get("forename") or "").strip()
    surname = (elements.get("surname") or "").strip()
    if forename and surname:
        full = f"{forename} {surname}"
    else:
        full = (data.get("name") or "").strip()
    full = full.strip()
    if not full:
        return None
    # Register names are usually upper-case; normalise to title case for display.
    return _title(full) if full.isupper() else full


def _iter_json_lines(path: Path):
    """Yield decoded JSON objects from a snapshot file (.txt of NDJSON, or a .zip of them)."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                with zf.open(member) as raw:
                    for line in io.TextIOWrapper(raw, encoding="utf-8", errors="replace"):
                        line = line.strip()
                        if line:
                            try:
                                yield json.loads(line)
                            except json.JSONDecodeError:
                                continue
    else:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


def _download(date: str) -> Path:
    """Download the dated snapshot zip to a temp file; raise with guidance on failure."""
    url = f"{BASE_URL}/persons-with-significant-control-snapshot-{date}.zip"
    print(f"Downloading {url} …", file=sys.stderr)
    tmp = Path(tempfile.gettempdir()) / f"psc-snapshot-{date}.zip"
    try:
        urllib.request.urlretrieve(url, tmp)  # noqa: S310 (known official host)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SystemExit(
            f"\nCould not download the PSC snapshot ({exc}).\n"
            f"The snapshot filename includes a release date that changes each publication, so\n"
            f"the automatic URL often 404s. Please download it manually and use --files:\n\n"
            f"  1. Open {BASE_URL}/en_pscdata.html\n"
            f"  2. Download 'persons-with-significant-control-snapshot-<date>.zip'\n"
            f"  3. python scripts/build_company_controllers.py --files <that-file.zip>\n"
        )
    return tmp


def _load_existing(path: Path) -> dict[str, str]:
    """Existing rows -> {name: role}, preserving comments is handled at write time."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip()
            if not first or first.startswith("#") or first.lower() == "name":
                continue
            out[first] = row[1].strip() if len(row) > 1 and row[1].strip() else ROLE
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--files", nargs="+", help="Local snapshot file(s): .zip or NDJSON .txt")
    ap.add_argument("--date", help="Snapshot date YYYY-MM-DD to try to download")
    ap.add_argument("--replace", action="store_true", help="Overwrite instead of merging with existing rows")
    ap.add_argument("--limit", type=int, default=0, help="Stop after N individual names (0 = all; for testing)")
    ap.add_argument("--out", default=str(UK_COMPANY_CONTROLLERS_FILE), help="Output CSV path")
    args = ap.parse_args()

    if not args.files and not args.date:
        raise SystemExit("Provide --files <snapshot> (recommended) or --date YYYY-MM-DD to download. See --help.")

    sources = [Path(f) for f in args.files] if args.files else [_download(args.date)]

    out_path = Path(args.out)
    names: dict[str, str] = {} if args.replace else _load_existing(out_path)
    seed_count = len(names)
    scanned = 0
    for src in sources:
        if not src.exists():
            raise SystemExit(f"Snapshot file not found: {src}")
        for rec in _iter_json_lines(src):
            scanned += 1
            if scanned % 500_000 == 0:
                print(f"  … {scanned:,} records, {len(names):,} names", file=sys.stderr)
            name = _name_from_record(rec)
            if name:
                names.setdefault(name, ROLE)
                if args.limit and (len(names) - seed_count) >= args.limit:
                    break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# UK company controllers — Companies House PSC / director name reference.\n"
        "# Regenerated by scripts/build_company_controllers.py from the free PSC snapshot.\n"
        "# Columns: name, role   (corroboration-only signal — see scoring/signals/companies_house.py)\n"
    )
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(header)
        w = csv.writer(fh)
        w.writerow(["name", "role"])
        for name in sorted(names):
            w.writerow([name, names[name]])

    print(
        f"Wrote {len(names):,} controller names to {out_path} "
        f"(scanned {scanned:,} PSC records; {seed_count:,} pre-existing rows kept).",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
