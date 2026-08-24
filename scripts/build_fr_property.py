"""Build the France area property-value reference table from open DVF data.

France publishes DVF ("Demandes de valeurs foncières"): the actual sale price of every
notarised property transaction, free and open on data.gouv.fr. This script streams the
geo-DVF yearly CSVs, aggregates residential sales to a median PRICE PER m² per code postal,
assigns a wealth tier, and writes reference_data/postcodes/fr_property_values.csv, which the
fr_property signal reads.

€/m² (not absolute price, as the UK table uses) because DVF mixes studios and houses in the
same postcode; per-m² is the standard French measure and is what separates the 7e from the
19e. Alsace-Moselle and Mayotte are absent from DVF (different land registry); keep any
curated rows for them — this script MERGES, preserving rows for postcodes it has no data for.

Stand-alone operator tool (NOT imported by the app). Standard library only. Ingest offline,
never a live lookup on a customer.

Usage
-----
    # Download the most recent full year and rebuild:
    python scripts/build_fr_property.py

    # Specific years (medians pool across them):
    python scripts/build_fr_property.py --years 2024 2023

    # Already-downloaded files (accepts .csv or .csv.gz, geo-dvf "full" layout):
    python scripts/build_fr_property.py --files /path/full-2024.csv.gz
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import statistics
import sys
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FR_PROPERTY_VALUES_FILE  # noqa: E402

# Tier bands in EUR per m² (area median). Calibrated so ultra ~= the 6e/7e/16e and the
# Riviera capes, prime ~= the rest of prime Paris + Neuilly + the best resorts, high ~= the
# strongest métropole districts.
ULTRA = 11_500
PRIME = 8_500
HIGH = 6_000

MIN_SALES = 30                     # per code postal, pooled across the chosen years
_PPM2_MIN, _PPM2_MAX = 500, 60_000  # discard data-entry absurdities
_RANK = {"ultra": 3, "prime": 2, "high": 1}

# Etalab's geo-DVF distribution: one national CSV per year.
_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{year}/full.csv.gz"

_RESIDENTIAL = {"maison", "appartement"}


def _tier(median: float) -> str | None:
    if median >= ULTRA:
        return "ultra"
    if median >= PRIME:
        return "prime"
    if median >= HIGH:
        return "high"
    return None


def _open_maybe_gz(path: Path):
    if str(path).endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", newline="")
    return open(path, newline="", encoding="utf-8")


def _ingest(path: Path, prices: dict[str, list[float]], areas: dict[str, str]) -> int:
    """Stream one geo-DVF file into the running per-postcode €/m² lists. Returns rows used."""
    used = 0
    with _open_maybe_gz(path) as fh:
        reader = csv.DictReader(fh)
        # One mutation (sale) can span several rows (lots); counting each residential row once
        # with its own surface is the standard flat approximation for area medians.
        for row in reader:
            if (row.get("nature_mutation") or "").strip().lower() != "vente":
                continue
            if (row.get("type_local") or "").strip().lower() not in _RESIDENTIAL:
                continue
            cp = (row.get("code_postal") or "").strip()
            if cp.endswith(".0"):
                cp = cp[:-2]
            cp = cp.zfill(5) if cp.isdigit() and len(cp) == 4 else cp
            if not (len(cp) == 5 and cp.isdigit()):
                continue
            try:
                price = float(row.get("valeur_fonciere") or 0)
                surface = float(row.get("surface_reelle_bati") or 0)
            except ValueError:
                continue
            if price <= 0 or surface < 9:
                continue
            ppm2 = price / surface
            if not (_PPM2_MIN <= ppm2 <= _PPM2_MAX):
                continue
            prices[cp].append(ppm2)
            commune = (row.get("nom_commune") or "").strip()
            if commune and cp not in areas:
                areas[cp] = commune
            used += 1
    return used


def _download(year: int, dest_dir: Path) -> Path:
    url = _URL.format(year=year)
    dest = dest_dir / f"dvf-full-{year}.csv.gz"
    print(f"Downloading {url} …")
    urllib.request.urlretrieve(url, dest)  # noqa: S310 — fixed https host
    return dest


def _existing_rows(path: Path) -> dict[str, list[str]]:
    """Current rows keyed by postcode, so curated/non-DVF coverage survives a rebuild."""
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip() and not row[0].startswith("#") and row[0].lower() != "code_postal":
                out[row[0].strip()] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--years", nargs="+", type=int, default=[2024])
    ap.add_argument("--files", nargs="+", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=Path(FR_PROPERTY_VALUES_FILE))
    args = ap.parse_args()

    prices: dict[str, list[float]] = defaultdict(list)
    areas: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as td:
        files = args.files or []
        if not files:
            for year in args.years:
                try:
                    files.append(_download(year, Path(td)))
                except urllib.error.URLError as exc:
                    print(f"Could not download {year}: {exc}", file=sys.stderr)
                    return 1
        total = 0
        for f in files:
            n = _ingest(Path(f), prices, areas)
            print(f"{f}: {n:,} residential sale rows used")
            total += n
    if not total:
        print("No usable rows found.", file=sys.stderr)
        return 1

    kept = _existing_rows(args.out)
    fresh = 0
    for cp, vals in prices.items():
        if len(vals) < MIN_SALES:
            continue
        med = statistics.median(vals)
        tier = _tier(med)
        if tier:
            kept[cp] = [cp, areas.get(cp, ""), str(int(med)), tier]
            fresh += 1
        else:
            kept.pop(cp, None)   # DVF says this area is no longer above the bands

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["code_postal", "area", "median_eur_m2", "tier"])
        fh.write("# Generated by scripts/build_fr_property.py from open DVF data (data.gouv.fr).\n")
        fh.write(f"# Tier bands (EUR/m² median): ultra>={ULTRA:,} prime>={PRIME:,} high>={HIGH:,}; "
                 f"min {MIN_SALES} sales per code postal.\n")
        for cp in sorted(kept):
            w.writerow(kept[cp])
    print(f"Wrote {len(kept):,} rows ({fresh:,} from DVF) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
