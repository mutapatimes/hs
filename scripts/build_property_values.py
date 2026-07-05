"""Build the UK area property-value reference table from HM Land Registry data.

HM Land Registry publishes "Price Paid Data": the actual sale price of (almost) every
residential property sold in England & Wales since 1995, free and open. This script
aggregates it to a median sale price per postcode OUTCODE (district), assigns a wealth
tier, and writes reference_data/postcodes/uk_property_values.csv, which the
property_value signal reads.

It is a stand-alone operator tool (NOT imported by the app or the tests). It uses only
the standard library so it runs anywhere.

Usage
-----
    # Download the two most recent yearly files and rebuild the table:
    python scripts/build_property_values.py

    # Use specific years:
    python scripts/build_property_values.py --years 2024 2023 2022

    # Use already-downloaded local CSV(s) instead of downloading:
    python scripts/build_property_values.py --files /path/pp-2024.csv /path/pp-2023.csv

Notes
-----
- Source files are large (~1GB each). The script streams them; it does not hold a file
  in memory, only the running per-outcode price lists.
- Tiers use absolute price bands (a "this is an expensive area" meaning that stays stable
  as you add years), tunable below. Only outcodes at/above the HIGH band are written, so
  the table stays compact.
- Scotland / Northern Ireland are not in this dataset; keep their rows curated by hand in
  the CSV (this script only overwrites England & Wales coverage if you let it; by default
  it MERGES, preserving any non-EW rows already present).
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import UK_PROPERTY_VALUES_FILE  # noqa: E402

# Tier bands in GBP (area median sale price). Tune to taste.
ULTRA = 1_500_000
PRIME = 900_000
HIGH = 600_000

# A robust median needs a few sales. Outcodes see hundreds; a single full postcode
# (~15 homes) sees only a handful, so it gets a lower bar.
MIN_SALES = 30       # per district (outcode) fallback row
MIN_SALES_PC = 4     # per exact full-postcode row
_RANK = {"ultra": 3, "prime": 2, "high": 1}

# HM Land Registry serves Price Paid Data from this S3 website endpoint. (The old
# vanity host prod.publicdata.landregistry.gov.uk no longer resolves.)
YEARLY_URL = "http://prod.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com/pp-{year}.csv"
# Land Registry Price Paid columns (headerless): 1 = price, 3 = postcode, 11 = town.
COL_PRICE, COL_POSTCODE, COL_TOWN = 1, 3, 11


def _outcode(postcode: str) -> str | None:
    pc = (postcode or "").strip().upper().replace(" ", "")
    if len(pc) <= 3:
        return None
    return pc[:-3]


def _full(postcode: str) -> str | None:
    """A real full postcode, spaceless, e.g. 'SW1A1AA'. None if it's not a full postcode."""
    pc = (postcode or "").strip().upper().replace(" ", "")
    return pc if len(pc) >= 5 else None


def _pretty(compact: str) -> str:
    """Re-insert the space for a readable CSV: 'SW1A1AA' -> 'SW1A 1AA'."""
    return f"{compact[:-3]} {compact[-3:]}"


def _tier(price: int) -> str | None:
    if price >= ULTRA:
        return "ultra"
    if price >= PRIME:
        return "prime"
    if price >= HIGH:
        return "high"
    return None


def _iter_rows(path: Path):
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.reader(fh):
            if len(row) > COL_TOWN:
                yield row


def _download(year: int) -> Path:
    url = YEARLY_URL.format(year=year)
    tmp = Path(tempfile.gettempdir()) / f"pp-{year}.csv"
    if tmp.exists() and tmp.stat().st_size > 0:
        print(f"  using cached {tmp}")
        return tmp
    print(f"  downloading {url} ...")
    try:
        urllib.request.urlretrieve(url, tmp)
    except (urllib.error.URLError, OSError) as exc:
        if tmp.exists():
            tmp.unlink()  # don't leave a half-written file behind
        raise SystemExit(
            f"\nCould not download {url}\n  reason: {exc}\n\n"
            "This is a network/DNS issue, not the script. Either your machine is offline,\n"
            "behind a VPN or captive-portal wifi, or DNS is blocked. Two options:\n"
            "  1. Fix connectivity (try another network / drop the VPN) and re-run.\n"
            "  2. Download the year file(s) manually from\n"
            "     https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads\n"
            "     then point the script at them:\n"
            "       python scripts/build_property_values.py --files ~/Downloads/pp-2024.csv\n"
        )
    return tmp


def _load_existing(path: Path) -> list[list[str]]:
    """Return existing data rows (so we can preserve hand-curated non-EW entries)."""
    if not path.exists():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and not row[0].startswith("#") and row[0].strip().lower() != "outcode":
                rows.append(row)
    return rows


def build(files: list[Path], merge: bool) -> None:
    oc_prices: dict[str, list[int]] = defaultdict(list)   # district (outcode) -> prices
    pc_prices: dict[str, list[int]] = defaultdict(list)   # exact full postcode -> prices
    towns: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for path in files:
        print(f"scanning {path.name} ...")
        n = 0
        for row in _iter_rows(path):
            oc = _outcode(row[COL_POSTCODE])
            if oc is None:
                continue
            try:
                price = int(row[COL_PRICE])
            except (TypeError, ValueError):
                continue
            oc_prices[oc].append(price)
            full = _full(row[COL_POSTCODE])
            if full:
                pc_prices[full].append(price)
            town = (row[COL_TOWN] or "").strip().title()
            if town:
                towns[oc][town] += 1
            n += 1
        print(f"  {n:,} sales")

    # Existing rows, so we can preserve hand-curated area labels and non-EW rows.
    existing = _load_existing(UK_PROPERTY_VALUES_FILE) if merge else []
    curated_area = {
        row[0].strip().upper().replace(" ", ""): row[1].strip()
        for row in existing if len(row) > 1 and row[1].strip()
    }

    def _area(oc: str) -> str:
        # Prefer a hand-curated district label (Land Registry's town is just "LONDON" for
        # every London outcode, losing the "Mayfair"/"Belgravia" feel), then the most common
        # town in the data, then the bare outcode.
        data_town = max(towns[oc].items(), key=lambda kv: kv[1])[0] if towns[oc] else oc
        return curated_area.get(oc) or data_town

    # District (outcode) rows — the fallback when there is no exact match.
    oc_rows: dict[str, list[str]] = {}
    for oc, plist in oc_prices.items():
        if len(plist) < MIN_SALES:
            continue
        med = int(statistics.median(plist))
        tier = _tier(med)
        if tier is None:
            continue
        oc_rows[oc] = [oc, _area(oc), str(med), tier]

    # Exact full-postcode rows — written ONLY where they add information beyond the district:
    # the district isn't listed at all (a valuable address on an ordinary street), or the
    # postcode is a stronger tier than its district. Keeps the table precise and compact.
    pc_rows: dict[str, list[str]] = {}
    for full, plist in pc_prices.items():
        if len(plist) < MIN_SALES_PC:
            continue
        med = int(statistics.median(plist))
        tier = _tier(med)
        if tier is None:
            continue
        oc = full[:-3]
        oc_tier = oc_rows.get(oc, [None, None, None, None])[3]
        if oc_tier is not None and _RANK[tier] <= _RANK[oc_tier]:
            continue   # the district already covers this at an equal-or-higher tier
        pc_rows[_pretty(full)] = [_pretty(full), _area(oc), str(med), tier]

    # Merge: keep existing rows the data did NOT cover (e.g. Scotland), then districts, then
    # exact postcodes (exact wins on key collision, though keys differ by shape anyway).
    final: dict[str, list[str]] = {}
    covered = set(oc_rows) | {k.replace(" ", "") for k in pc_rows}
    for row in existing:
        key = row[0].strip().upper().replace(" ", "")
        if key not in covered:
            final[key] = row
    for oc, row in oc_rows.items():
        final[oc] = row
    for k, row in pc_rows.items():
        final[k.replace(" ", "")] = row

    ordered = sorted(final.values(), key=lambda r: -int(r[2]))
    out = UK_PROPERTY_VALUES_FILE
    with out.open("w", newline="", encoding="utf-8") as fh:
        fh.write("postcode,area,median_price,tier\n")
        fh.write("# Generated by scripts/build_property_values.py from HM Land Registry "
                 "Price Paid Data. 'postcode' is a full postcode (exact match) or an outcode "
                 "(district fallback).\n")
        fh.write(f"# Tier bands (GBP median): ultra>={ULTRA:,} prime>={PRIME:,} high>={HIGH:,}; "
                 f"min {MIN_SALES} sales per district, {MIN_SALES_PC} per exact postcode.\n")
        w = csv.writer(fh)
        for row in ordered:
            w.writerow(row)
    print(f"\nwrote {len(ordered):,} rows ({len(pc_rows):,} exact postcodes, "
          f"{len(oc_rows):,} districts) to {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", nargs="+", type=int, help="Years to download (default: 2 most recent).")
    ap.add_argument("--files", nargs="+", type=Path, help="Local Price Paid CSV(s) to use instead of downloading.")
    ap.add_argument("--no-merge", action="store_true",
                    help="Do not preserve existing hand-curated rows (e.g. Scotland/NI).")
    args = ap.parse_args()

    if args.files:
        files = args.files
    else:
        years = args.years or [2024, 2023]
        files = [_download(y) for y in years]

    build(files, merge=not args.no_merge)


if __name__ == "__main__":
    main()
