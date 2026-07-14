"""Build the US high-value home-area reference table from Zillow ZHVI ZIP data.

Zillow publishes the Zillow Home Value Index (ZHVI) per ZIP code as a free monthly time series.
This script takes each ZIP's LATEST ZHVI, assigns a wealth tier, and writes
reference_data/postcodes/us_property_values.csv, which the ``us_property`` signal reads. Home value
is a WEALTH FACT (on by default, not an origin proxy). The US analog to build_property_values.py
(which does the same for the UK from HM Land Registry).

Stand-alone operator tool (NOT imported by the app or tests). Standard library only.

Download the data first (free, no login):
    Zillow Research  ->  zillow.com/research/data
    Home Values -> "ZHVI All Homes (SFR, Condo/Co-op) Time Series ($)"
    Geography dropdown: "ZIP Code"
    file: Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv

Usage
-----
    python scripts/build_us_property.py --file ~/Downloads/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
    python scripts/build_us_property.py --file <path> --min-value 1000000

Notes
-----
- Tier by latest ZHVI: ultra >= $2M, prime >= --min-value (default $1M). Only prime+ ZIPs are
  written: a $1M+ median-home ZIP is a genuine wealth area (the US median home is ~$350k), so the
  signal stays appropriately strong and the table stays compact.
- The raw $ value is written for auditing but the signal only ever surfaces a TIER grade, never a
  price. Area label = the ZIP's City + State from the file.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # make repo-root `config` importable
from config import US_PROPERTY_VALUES_FILE  # noqa: E402

_ULTRA = 2_000_000


def _zip5(value: object) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:5] if len(digits) >= 5 else None


def _is_date(col: str) -> bool:
    return bool(col) and len(col) == 10 and col[4] == "-" and col[7] == "-" and col[:4].isdigit()


def _latest_value(row: dict, date_cols: list[str]) -> float | None:
    """The most recent non-empty ZHVI in the row."""
    for c in reversed(date_cols):
        v = row.get(c, "")
        if v not in ("", None):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _tier(value: float, min_value: int) -> str | None:
    if value >= _ULTRA:
        return "ultra"
    if value >= min_value:
        return "prime"
    return None


def build(reader: csv.DictReader, min_value: int) -> dict[str, tuple]:
    """reader: DictReader over the Zillow ZIP ZHVI CSV. -> {zip5: (area, value, tier)}."""
    date_cols = [c for c in (reader.fieldnames or []) if _is_date(c)]
    out: dict[str, tuple] = {}
    for row in reader:
        z = _zip5(row.get("RegionName"))
        if not z:
            continue
        val = _latest_value(row, date_cols)
        if val is None:
            continue
        tier = _tier(val, min_value)
        if not tier:
            continue
        city, state = (row.get("City") or "").strip(), (row.get("State") or "").strip()
        area = f"{city} {state}".strip() if city else state
        out[z] = (area, int(round(val)), tier)
    return out


def write_table(path: Path, rows: dict[str, tuple]) -> None:
    lines = [
        "zip,area,value,tier",
        "# US high-value home-area ZIPs (Zillow ZHVI). Regenerate with scripts/build_us_property.py.",
        "# Lines starting with # are ignored. Tier: ultra (>= $2M) / prime (>= $1M) latest ZHVI.",
    ]
    for z in sorted(rows):
        area, val, tier = rows[z]
        lines.append(f"{z},{area},{val},{tier}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the US home-value ZIP tiers from Zillow ZHVI.")
    ap.add_argument("--file", type=Path, required=True, help="Zillow Zip_zhvi ...month.csv")
    ap.add_argument("--min-value", type=int, default=1_000_000, help="Min latest ZHVI to keep (default 1000000).")
    ap.add_argument("--out", type=Path, default=US_PROPERTY_VALUES_FILE)
    args = ap.parse_args()

    with args.file.open(newline="", encoding="utf-8") as fh:
        rows = build(csv.DictReader(fh), args.min_value)
    write_table(args.out, rows)
    ultra = sum(1 for _, _, t in rows.values() if t == "ultra")
    print(f"Wrote {len(rows)} ZIPs to {args.out} "
          f"({ultra} ultra >= $2M, {len(rows) - ultra} prime >= ${args.min_value:,}).")


if __name__ == "__main__":
    main()
