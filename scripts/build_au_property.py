"""Build the Australia postcode property-value table from NSW Valuer General open data.

The NSW Valuer General publishes every NSW property sale as bulk "Property Sales Information"
(PSI) downloads. The download site sits behind a Cloudflare browser check, so this script
takes ALREADY-DOWNLOADED files: open https://valuation.property.nsw.gov.au/embed/
propertySalesInformation in a browser, download a yearly archive (a zip of weekly zips of
.DAT files), then:

    python scripts/build_au_property.py --files ~/Downloads/2025.zip

It aggregates HOUSE sales (non-strata residential; houses are what separates Point Piper from
a units-heavy corridor) to a median AUD price per postcode, assigns tiers, and MERGES into
reference_data/postcodes/au_property_values.csv — curated rows for the states whose registers
are commercial (VIC/QLD/WA/SA/ACT/TAS) survive, since NSW data never mentions their
postcodes. Stand-alone operator tool; stdlib only.

PSI "B" record layout (2001+ format, ';'-separated):
    B;district;propertyId;saleCounter;downloaded;propertyName;unitNo;houseNo;street;
    locality;postcode;area;areaType;contractDate;settlementDate;price;zoning;nature;
    primaryPurpose;strataLotNo;componentCode;saleCode;interestOfSale;dealingNumber
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AU_PROPERTY_VALUES_FILE  # noqa: E402

# Tier bands in AUD (postcode median HOUSE price). Sydney's overall house median is ~1.6m;
# these bands mark the genuinely prime end.
ULTRA = 4_500_000
PRIME = 3_000_000
HIGH = 2_200_000

MIN_SALES = 25
_PRICE_MIN, _PRICE_MAX = 150_000, 100_000_000
_RANK = {"ultra": 3, "prime": 2, "high": 1}

_POSTCODE_IX, _LOCALITY_IX = 10, 9
_PRICE_IX, _NATURE_IX, _PURPOSE_IX, _STRATA_IX, _INTEREST_IX = 15, 17, 18, 19, 22


def _tier(median: float) -> str | None:
    if median >= ULTRA:
        return "ultra"
    if median >= PRIME:
        return "prime"
    if median >= HIGH:
        return "high"
    return None


def _ingest_dat(fh, prices: dict[str, list[float]], areas: dict[str, str]) -> int:
    used = 0
    for line in fh:
        parts = line.rstrip("\r\n").split(";")
        if len(parts) < 20 or parts[0] != "B":
            continue
        pc = parts[_POSTCODE_IX].strip()
        if not (len(pc) == 4 and pc.isdigit()):
            continue
        nature = parts[_NATURE_IX].strip().upper()
        purpose = parts[_PURPOSE_IX].strip().upper()
        if nature != "R" and "RESIDEN" not in purpose:
            continue
        if parts[_STRATA_IX].strip():          # strata lot -> unit; houses only
            continue
        interest = parts[_INTEREST_IX].strip() if len(parts) > _INTEREST_IX else ""
        if interest not in ("", "0", "100"):   # part-share transfers skew medians
            continue
        try:
            price = float(parts[_PRICE_IX] or 0)
        except ValueError:
            continue
        if not (_PRICE_MIN <= price <= _PRICE_MAX):
            continue
        prices[pc].append(price)
        locality = parts[_LOCALITY_IX].strip().title()
        if locality and pc not in areas:
            areas[pc] = locality
        used += 1
    return used


def _walk(path: Path, prices: dict[str, list[float]], areas: dict[str, str]) -> int:
    """Ingest a .DAT file, or a zip of .DAT files / nested zips (the yearly layout)."""
    if path.suffix.lower() == ".zip":
        used = 0
        with zipfile.ZipFile(path) as zf:
            used += _walk_zip(zf, prices, areas)
        return used
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        return _ingest_dat(fh, prices, areas)


def _walk_zip(zf: zipfile.ZipFile, prices, areas) -> int:
    used = 0
    for name in zf.namelist():
        low = name.lower()
        if low.endswith(".zip"):
            with zf.open(name) as inner:
                with zipfile.ZipFile(io.BytesIO(inner.read())) as izf:
                    used += _walk_zip(izf, prices, areas)
        elif low.endswith(".dat"):
            with zf.open(name) as fh:
                used += _ingest_dat(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"),
                                    prices, areas)
    return used


def _existing_rows(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip() and not row[0].startswith("#") and row[0].lower() != "postcode":
                out[row[0].strip()] = row
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="+", type=Path, required=True,
                    help="Downloaded PSI yearly/weekly .zip archives or loose .DAT files")
    ap.add_argument("--out", type=Path, default=Path(AU_PROPERTY_VALUES_FILE))
    args = ap.parse_args()

    prices: dict[str, list[float]] = defaultdict(list)
    areas: dict[str, str] = {}
    total = 0
    for f in args.files:
        n = _walk(Path(f), prices, areas)
        print(f"{f}: {n:,} house sale rows used")
        total += n
    if not total:
        print("No usable rows found.", file=sys.stderr)
        return 1

    kept = _existing_rows(args.out)
    fresh = 0
    for pc, vals in prices.items():
        if len(vals) < MIN_SALES:
            continue
        med = statistics.median(vals)
        tier = _tier(med)
        if tier:
            kept[pc] = [pc, areas.get(pc, ""), str(int(med)), tier]
            fresh += 1
        else:
            kept.pop(pc, None)   # the data says this NSW postcode is below the bands now

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["postcode", "area", "median_aud", "tier"])
        fh.write("# NSW rows generated by scripts/build_au_property.py from Valuer General bulk sales.\n")
        fh.write(f"# Tier bands (AUD house median): ultra>={ULTRA:,} prime>={PRIME:,} high>={HIGH:,}; "
                 f"min {MIN_SALES} sales per postcode. Curated non-NSW rows are preserved.\n")
        for pc in sorted(kept):
            w.writerow(kept[pc])
    print(f"Wrote {len(kept):,} rows ({fresh:,} from PSI) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
