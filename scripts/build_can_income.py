"""Build the Canada FSA income table from CRA open taxation statistics.

The Canada Revenue Agency publishes annual Individual Tax Statistics by Forward Sortation
Area on canada.ca (catalogued on open.canada.ca): taxfiler counts and total income per FSA
for the whole country. This script downloads the Canada-wide Table 1a (or takes a local
copy), computes AVERAGE TOTAL INCOME per FSA, assigns wealth tiers, and writes
reference_data/postcodes/can_income_values.csv, which the can_income signal reads.

The table is national and complete, so the output is fully regenerated each run. FSAs with
few filers are excluded: downtown office FSAs (K1P, Ottawa's parliamentary district) show
absurd averages from a handful of business-address filers. Stdlib only; ingest offline,
never a live lookup on a customer.

Usage
-----
    python scripts/build_can_income.py
    python scripts/build_can_income.py --files ~/Downloads/tbl1a-en.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CAN_INCOME_VALUES_FILE  # noqa: E402

# Tier bands in CAD (FSA average total income). Calibrated on the 2021 national distribution:
# the median FSA averages ~$55k; ultra >= 200k catches 6 FSAs (Westmount, Rosedale, Lawrence
# Park, Moore Park, Forest Hill South, the Financial District), prime ~18, high ~31.
ULTRA = 200_000
PRIME = 140_000
HIGH = 100_000

MIN_FILERS = 2_500   # thin FSAs give office-address-distorted averages

# CRA Individual Tax Statistics by FSA, 2023 edition (2021 tax year), Canada-wide Table 1a.
_URL = ("https://www.canada.ca/content/dam/cra-arc/prog-policy/stats/"
        "individual-tax-stats-fsa/2021-tax-year/tbl1a-en.csv")

# Neighbourhood names for the FSAs that clear the bands, so reasons read "Rosedale, Toronto"
# rather than a bare code. Fallback for unnamed FSAs is the regional city from the first letter.
NAMES = {
    "M5H": "Financial District, Toronto", "H3Y": "Westmount, Montreal",
    "M4N": "Lawrence Park, Toronto", "M4T": "Moore Park, Toronto",
    "M4W": "Rosedale, Toronto", "M4V": "Forest Hill South, Toronto",
    "M5C": "Downtown Toronto", "T3Z": "Springbank, Calgary",
    "V7V": "West Vancouver", "V7W": "West Vancouver", "V7S": "British Properties, West Vancouver",
    "V7R": "Edgemont, North Vancouver", "M5P": "Forest Hill, Toronto",
    "M8X": "The Kingsway, Toronto", "T2S": "Elbow Park, Calgary",
    "M5R": "The Annex & Yorkville, Toronto", "L6J": "Old Oakville",
    "V6C": "Coal Harbour, Vancouver", "M5M": "Bedford Park, Toronto",
    "M4G": "Leaside, Toronto", "M2P": "York Mills, Toronto",
    "M5N": "Lytton Park, Toronto", "M4R": "North Toronto",
    "H3R": "Mount Royal, Montreal", "M2L": "St Andrew-Windfields, Toronto",
    "T2T": "Upper Mount Royal, Calgary", "M3B": "Banbury & Don Mills, Toronto",
    "K1M": "Rockcliffe Park, Ottawa", "L0J": "Kleinburg", "H3Z": "Westmount, Montreal",
    "H2Y": "Old Montreal", "H3P": "Town of Mount Royal, Montreal",
    "V6N": "Kerrisdale & Dunbar, Vancouver", "V6H": "Shaughnessy, Vancouver",
    "L7B": "King City", "L5H": "Lorne Park, Mississauga", "V6R": "Point Grey, Vancouver",
    "M5E": "St Lawrence, Toronto", "T2N": "Hillhurst, Calgary", "M4E": "The Beaches, Toronto",
    "V6J": "Kitsilano, Vancouver", "H3A": "Golden Square Mile, Montreal",
    "M9A": "Islington, Toronto", "H3G": "Downtown Montreal", "V6L": "Dunbar, Vancouver",
    "M6S": "Swansea & Bloor West, Toronto", "M5J": "Harbourfront, Toronto",
    "H9W": "Beaconsfield, Montreal", "R3P": "Tuxedo, Winnipeg", "T9K": "Timberlea, Fort McMurray",
    "H2V": "Outremont, Montreal", "T3H": "West Springs, Calgary", "K1S": "The Glebe, Ottawa",
    "G1T": "Sillery, Quebec City", "T8B": "Sherwood Park",
}
_REGION = {"A": "Newfoundland", "B": "Nova Scotia", "C": "Prince Edward Island",
           "E": "New Brunswick", "G": "Quebec", "H": "Montreal", "J": "Quebec",
           "K": "Eastern Ontario", "L": "Greater Toronto", "M": "Toronto",
           "N": "Southwestern Ontario", "P": "Northern Ontario", "R": "Manitoba",
           "S": "Saskatchewan", "T": "Alberta", "V": "British Columbia",
           "X": "Northern Canada", "Y": "Yukon"}


def _tier(avg: float) -> str | None:
    if avg >= ULTRA:
        return "ultra"
    if avg >= PRIME:
        return "prime"
    if avg >= HIGH:
        return "high"
    return None


def _ingest(path: Path, out: dict[str, float]) -> int:
    used = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if len(row) < 4:
                continue
            fsa = row[1].strip().upper()
            if len(fsa) != 3 or not (fsa[0].isalpha() and fsa[1].isdigit() and fsa[2].isalpha()):
                continue
            try:
                filers = float(row[2])
                total = float(row[3]) * 1000   # CRA publishes income in $000s
            except ValueError:
                continue
            if filers < MIN_FILERS or total <= 0:
                continue
            out[fsa] = total / filers
            used += 1
    return used


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="+", type=Path, default=None,
                    help="Already-downloaded CRA Table 1a CSV(s)")
    ap.add_argument("--out", type=Path, default=Path(CAN_INCOME_VALUES_FILE))
    args = ap.parse_args()

    stats: dict[str, float] = {}
    with tempfile.TemporaryDirectory() as td:
        files = args.files or []
        if not files:
            dest = Path(td) / "cra_tbl1a.csv"
            print(f"Downloading {_URL} …")
            try:
                urllib.request.urlretrieve(_URL, dest)  # noqa: S310 — fixed https host
            except urllib.error.URLError as exc:
                print(f"Could not download: {exc}", file=sys.stderr)
                return 1
            files = [dest]
        total = 0
        for f in files:
            n = _ingest(Path(f), stats)
            print(f"{f}: {n:,} FSAs read")
            total += n
    if not total:
        print("No usable rows found.", file=sys.stderr)
        return 1

    rows = []
    for fsa, avg in stats.items():
        tier = _tier(avg)
        if tier:
            name = NAMES.get(fsa) or f"{_REGION.get(fsa[0], 'Canada')} {fsa}"
            rows.append([fsa, name, str(int(avg)), tier])
    rows.sort(key=lambda r: r[0])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["fsa", "area", "avg_total_income", "tier"])
        fh.write("# Generated by scripts/build_can_income.py from CRA FSA tax statistics (canada.ca).\n")
        fh.write(f"# Tier bands (CAD average total income): ultra>={ULTRA:,} prime>={PRIME:,} "
                 f"high>={HIGH:,}; min {MIN_FILERS:,} taxfilers per FSA.\n")
        w.writerows(rows)
    print(f"Wrote {len(rows):,} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
