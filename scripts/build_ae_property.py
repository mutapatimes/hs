"""Build the UAE community property-value table from Dubai Land Department open data.

The DLD publishes every Dubai property transaction as open data ("DLD Transactions" on
Dubai Pulse). Dubai Pulse refuses connections from non-UAE server IPs, so this script takes
an ALREADY-DOWNLOADED file: open https://www.dubaipulse.gov.ae/data/dld-transactions/
dld_transactions-open in a browser, download the CSV (large; all years), then:

    python scripts/build_ae_property.py --files ~/Downloads/transactions.csv

It aggregates residential SALES to a median AED/sqm per community, maps the DLD's cadastral
area names to the names customers actually write in addresses (Marsa Dubai -> Dubai Marina),
assigns tiers, and MERGES into reference_data/locations/ae_property_values.csv — curated rows
the data cannot see (Abu Dhabi; new launches) survive. Stand-alone operator tool; stdlib only.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AE_PROPERTY_VALUES_FILE  # noqa: E402

# Tier bands in AED per sqm (community median). Prime Dubai trades ~20-35k AED/sqm.
ULTRA = 28_000
PRIME = 20_000
HIGH = 15_000

MIN_SALES = 50
_PPS_MIN, _PPS_MAX = 3_000, 150_000
_RANK = {"ultra": 3, "prime": 2, "high": 1}

# DLD cadastral area -> the name customers write. Only areas whose cadastral name would not
# be recognised in an address; identity for everything else.
ALIASES = {
    "marsa dubai": "Dubai Marina",
    "burj khalifa": "Downtown Dubai",
    "hadaeq sheikh mohammed bin rashid": "Dubai Hills Estate",
    "al merkadh": "District One",
    "al khairan first": "Dubai Creek Harbour",
    "madinat hind 4": "Damac Hills 2",
    "al hebiah fourth": "Damac Hills",
    "al thanyah third": "Emirates Hills",
    "al thanyah fourth": "Jumeirah Lake Towers",
    "al thanyah fifth": "Jumeirah Golf Estates",
    "me'aisem first": "Jumeirah Village Circle",
    "al yelayiss 2": "Town Square",
    "wadi al safa 5": "Jumeirah Village Triangle",
    "island 2": "Jumeirah Bay Island",
    "jumeirah second": "Pearl Jumeira",
    "um suqaim third": "Umm Suqeim",
}


def _tier(median: float) -> str | None:
    if median >= ULTRA:
        return "ultra"
    if median >= PRIME:
        return "prime"
    if median >= HIGH:
        return "high"
    return None


def _ingest(path: Path, prices: dict[str, list[float]]) -> int:
    used = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if "sales" not in (row.get("trans_group_en") or "").strip().lower():
                continue
            usage = (row.get("property_usage_en") or "").strip().lower()
            if usage and "residential" not in usage:
                continue
            area = (row.get("area_name_en") or "").strip()
            if not area:
                continue
            try:
                worth = float(row.get("actual_worth") or 0)
                size = float(row.get("procedure_area") or 0)
            except ValueError:
                continue
            if worth <= 0 or size < 15:
                continue
            pps = worth / size
            if not (_PPS_MIN <= pps <= _PPS_MAX):
                continue
            name = ALIASES.get(area.lower(), area)
            prices[name].append(pps)
            used += 1
    return used


def _existing_rows(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip() and not row[0].startswith("#") and row[0].lower() != "area":
                out[row[0].strip().lower()] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="+", type=Path, required=True,
                    help="Downloaded DLD transactions CSV(s)")
    ap.add_argument("--out", type=Path, default=Path(AE_PROPERTY_VALUES_FILE))
    args = ap.parse_args()

    prices: dict[str, list[float]] = defaultdict(list)
    total = 0
    for f in args.files:
        n = _ingest(Path(f), prices)
        print(f"{f}: {n:,} residential sale rows used")
        total += n
    if not total:
        print("No usable rows found.", file=sys.stderr)
        return 1

    kept = _existing_rows(args.out)
    fresh = 0
    for name, vals in prices.items():
        if len(vals) < MIN_SALES:
            continue
        med = statistics.median(vals)
        tier = _tier(med)
        key = name.lower()
        if tier:
            kept[key] = [name, "Dubai", str(int(med)), tier]
            fresh += 1
        elif key in kept and (kept[key][1] or "").lower() == "dubai":
            kept.pop(key)   # the data says this Dubai area is below the bands now

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["area", "emirate", "median_aed_sqm", "tier"])
        fh.write("# Generated by scripts/build_ae_property.py from DLD open transaction data.\n")
        fh.write(f"# Tier bands (AED/sqm median): ultra>={ULTRA:,} prime>={PRIME:,} high>={HIGH:,}; "
                 f"min {MIN_SALES} sales per community. Curated non-Dubai rows are preserved.\n")
        for key in sorted(kept):
            w.writerow(kept[key])
    print(f"Wrote {len(kept):,} rows ({fresh:,} from DLD) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
