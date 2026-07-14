"""Build the US high-income ZIP list from IRS Statistics of Income (SOI) ZIP-code data.

The IRS publishes, per ZIP code, the number of tax returns and the total Adjusted Gross Income
(AGI) in each income bracket — free and public domain (a US federal-government work). This script
aggregates it to a MEAN AGI per ZIP, keeps the genuinely high-income ZIPs, and merges them into
``reference_data/postcodes/us_hnwi_zips.csv``, which the ``us_zip`` signal reads. Mean household
income is a WEALTH FACT, so this is on by default; it is not an origin proxy.

It replaces a hand-picked list of ~50 ZIPs with comprehensive, defensible, data-driven coverage —
the US equivalent of what ``build_property_values.py`` does for the UK from HM Land Registry.

Stand-alone operator tool (NOT imported by the app or tests). Standard library only.

Download the data first (one national CSV, ~50 MB):
    IRS  ->  SOI Tax Stats  ->  Individual Income Tax Statistics  ->  ZIP Code Data (SOI)
    https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-zip-code-data-soi
    e.g. the file "21zpallagi.csv" (tax year 2021).

Usage
-----
    python scripts/build_us_zips.py --files ~/Downloads/21zpallagi.csv
    python scripts/build_us_zips.py --files 21zpallagi.csv --min-agi 250000 --min-returns 100
    python scripts/build_us_zips.py --files 21zpallagi.csv --no-merge   # replace, don't keep curated

Notes
-----
- ``A00100`` is total AGI in THOUSANDS of dollars; ``N1`` is the number of returns. Mean AGI for a
  ZIP = (sum of A00100 across brackets) * 1000 / (sum of N1). Passing several years just widens
  the sample (a multi-year weighted mean).
- Default keeps ZIPs with mean AGI >= $250k and >= 100 returns — genuinely wealthy areas, so the
  weight-3 ``us_zip`` signal stays appropriate. Tune with --min-agi / --min-returns.
- MERGES by default: existing curated rows (with their neighbourhood names, e.g. "Beverly Hills")
  are preserved; newly-added ZIPs get their state as the area label. --no-merge replaces instead.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # make repo-root `config` importable
from config import US_HNWI_ZIPS_FILE  # noqa: E402

_SKIP_ZIPS = {"00000", "99999"}   # IRS state-total / "other" aggregate rows, not real ZIPs


def _zip5(value: object) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:5] if len(digits) >= 5 else None


def _cell(row: dict, *names: str):
    """Case-insensitive column access over an IRS SOI row (headers vary in case)."""
    for k in row:
        if k.lower() in names:
            return row[k]
    return None


def aggregate_irs(rows) -> dict[str, dict]:
    """Sum returns + AGI across income brackets per ZIP.

    rows: an iterable of dict rows (IRS SOI zpallagi). Returns {zip5: {returns, agi_k, state}}.
    """
    agg: dict[str, dict] = {}
    for row in rows:
        z = _zip5(_cell(row, "zipcode", "zip"))
        if not z or z in _SKIP_ZIPS:
            continue
        try:
            n1 = float(_cell(row, "n1") or 0)
            agi_k = float(_cell(row, "a00100") or 0)
        except (TypeError, ValueError):
            continue
        e = agg.setdefault(z, {"returns": 0.0, "agi_k": 0.0, "state": ""})
        e["returns"] += n1
        e["agi_k"] += agi_k
        state = str(_cell(row, "state") or "").strip().upper()
        if len(state) == 2 and not e["state"]:
            e["state"] = state
    return agg


def select_high_income(agg: dict[str, dict], min_agi: int, min_returns: int) -> dict[str, tuple]:
    """Keep ZIPs above the thresholds. Returns {zip5: (mean_agi:int, state:str)}."""
    out: dict[str, tuple] = {}
    for z, e in agg.items():
        if e["returns"] < min_returns:
            continue
        mean = e["agi_k"] * 1000.0 / e["returns"] if e["returns"] else 0.0
        if mean >= min_agi:
            out[z] = (int(round(mean)), e["state"])
    return out


def load_existing(path: Path) -> tuple[list[str], dict[str, str]]:
    """Preserve comment/header lines; return (header_lines, {zip: area})."""
    header: list[str] = []
    rows: dict[str, str] = {}
    if not path.exists():
        return header, rows
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.lower().startswith("zip,") or s.lower() == "zip":
            header.append(line)
            continue
        parts = [p.strip() for p in s.split(",")]
        z = _zip5(parts[0])
        if z:
            rows[z] = parts[1] if len(parts) > 1 else ""
    return header, rows


def merge_rows(existing: dict[str, str], selected: dict[str, tuple],
               keep_existing: bool) -> dict[str, tuple]:
    """-> {zip: (area, mean_agi_or_empty)}. Curated area names win over state labels."""
    out: dict[str, tuple] = {}
    if keep_existing:
        for z, area in existing.items():
            out[z] = (area, "")
    for z, (mean, state) in selected.items():
        area = out[z][0] if (z in out and out[z][0]) else state   # keep a curated neighbourhood name
        out[z] = (area, str(mean))
    return out


def write_table(path: Path, header: list[str], rows: dict[str, tuple]) -> None:
    lines = header[:] or [
        "zip,area,mean_agi",
        "# US high-income ZIP codes (HNWI signal), from IRS SOI ZIP-code data.",
        "# Regenerate with scripts/build_us_zips.py. Lines starting with # are ignored.",
    ]
    for z in sorted(rows):
        area, mean = rows[z]
        lines.append(f"{z},{area},{mean}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the US high-income ZIP list from IRS SOI data.")
    ap.add_argument("--files", nargs="+", type=Path, required=True,
                    help="IRS SOI zpallagi CSV file(s), e.g. 21zpallagi.csv.")
    ap.add_argument("--min-agi", type=int, default=250_000, help="Min mean AGI to keep (default 250000).")
    ap.add_argument("--min-returns", type=int, default=100, help="Min returns per ZIP (default 100).")
    ap.add_argument("--no-merge", action="store_true", help="Replace the file instead of preserving curated rows.")
    ap.add_argument("--out", type=Path, default=US_HNWI_ZIPS_FILE)
    args = ap.parse_args()

    agg: dict[str, dict] = {}
    for f in args.files:
        with f.open(newline="", encoding="utf-8") as fh:
            for z, e in aggregate_irs(csv.DictReader(fh)).items():
                a = agg.setdefault(z, {"returns": 0.0, "agi_k": 0.0, "state": ""})
                a["returns"] += e["returns"]
                a["agi_k"] += e["agi_k"]
                a["state"] = a["state"] or e["state"]

    selected = select_high_income(agg, args.min_agi, args.min_returns)
    header, existing = load_existing(args.out)
    rows = merge_rows(existing, selected, keep_existing=not args.no_merge)
    write_table(args.out, header, rows)
    print(f"Wrote {len(rows)} ZIPs to {args.out} "
          f"({len(selected)} from IRS at >= ${args.min_agi:,} mean AGI, >= {args.min_returns} returns).")


if __name__ == "__main__":
    main()
