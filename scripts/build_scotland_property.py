"""Merge curated Scottish prime-area rows into the UK property-value table.

Scotland is NOT in HM Land Registry Price Paid Data (that covers England & Wales only), and
Registers of Scotland sells its transaction-level data — there is no free address-level bulk
feed to bake the way build_property_values.py bakes England & Wales. What IS open is the
Scottish Government's aggregate house-price statistics at intermediate-zone (S02) granularity
on statistics.gov.scot, which objectively rank Scotland's wealthiest micro-areas.

This script writes a curated set of Scottish OUTCODE rows at PRIME tier, grounded in those
official zone medians, and merges them into reference_data/postcodes/uk_property_values.csv
(the build_property_values.py merge already preserves non-England/Wales rows, so a later UK
rebake keeps them). Prime, not high, on purpose: the UK tier bands are London-calibrated
(prime >= GBP 900k median), but Scotland's genuinely-prime areas sit at GBP 350-550k, which
would fall into the 'high' band that is deliberately suppressed at district level (a whole
'high' outcode is noise in London). Tiering these relative to Scotland's own distribution and
writing them as prime is what lets a real Edinburgh New Town address score.

Refresh the underlying figures with this SPARQL query against https://statistics.gov.scot/sparql
(Accept: text/csv), then update MEDIANS below if they have moved materially:

    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?label ?median WHERE {
      ?o <http://purl.org/linked-data/cube#dataSet>
           <http://statistics.gov.scot/data/house-sales-prices> ;
         <http://purl.org/linked-data/sdmx/2009/dimension#refArea> ?area ;
         <http://purl.org/linked-data/sdmx/2009/dimension#refPeriod>
           <http://reference.data.gov.uk/id/year/2018> ;
         <http://statistics.gov.scot/def/measure-properties/median> ?median .
      ?area rdfs:label ?label .
      FILTER(STRSTARTS(STR(?area),
        'http://statistics.gov.scot/id/statistical-geography/S02'))
    } ORDER BY DESC(?median)

Stand-alone operator tool (NOT imported by the app). Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import UK_PROPERTY_VALUES_FILE  # noqa: E402

# Curated Scottish prime outcodes: (outcode, area label, representative median GBP, tier).
# Median = the top constituent S02 intermediate-zone median (statistics.gov.scot, 2018), the
# same year across all rows. Only DOMINANTLY affluent outcodes are listed — mixed outcodes
# (e.g. EH14 pairs Craiglockhart with Wester Hailes) are deliberately omitted rather than
# risk firing on their non-prime half. All prime: Scotland's ceiling is ~GBP 540k, below the
# UK 'ultra' band, and prime is the honest grade for these areas.
SCOTLAND = [
    # Edinburgh
    ("EH3", "Edinburgh New Town", 430000),
    ("EH4", "Edinburgh (Murrayfield, Ravelston & Cramond)", 540000),
    ("EH9", "Edinburgh (The Grange & Marchmont)", 431000),
    ("EH10", "Edinburgh (Morningside & Merchiston)", 450000),
    ("EH12", "Edinburgh (Murrayfield & Corstorphine)", 340000),
    ("EH13", "Edinburgh (Colinton & Fairmilehead)", 384000),
    ("EH15", "Edinburgh (Joppa & Portobello)", 350000),
    ("EH5", "Edinburgh (Trinity)", 317000),
    # East Lothian
    ("EH39", "North Berwick", 357000),
    ("EH31", "Gullane", 400000),
    # Fife
    ("KY16", "St Andrews", 340000),
    # East Renfrewshire / East Dunbartonshire
    ("G77", "Newton Mearns", 333000),
    ("G46", "Giffnock & Whitecraigs", 407000),
    ("G61", "Bearsden", 343000),
    ("G62", "Milngavie", 322000),
    # Glasgow West End
    ("G12", "Glasgow West End (Dowanhill & Kelvinside)", 315000),
    # Aberdeen
    ("AB15", "Aberdeen West (Cults & Rubislaw)", 361000),
]
TIER = "prime"


def _load(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(UK_PROPERTY_VALUES_FILE))
    args = ap.parse_args()
    if not args.out.exists():
        print(f"UK property table not found: {args.out}", file=sys.stderr)
        return 1

    rows = _load(args.out)
    header = [r for r in rows if r and (r[0].startswith("#") or r[0].lower() == "postcode")]
    body = [r for r in rows if r and not r[0].startswith("#") and r[0].lower() != "postcode"]

    curated = {oc.upper(): [oc, area, str(med), TIER] for oc, area, med in SCOTLAND}
    kept = [r for r in body if r[0].strip().upper().replace(" ", "") not in curated]
    kept.extend(curated.values())
    kept.sort(key=lambda r: -int(r[2]) if len(r) > 2 and r[2].lstrip("-").isdigit() else 0)

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        for h in header:
            if h[0].startswith("#"):
                fh.write(("," .join(h) if len(h) > 1 else h[0]) + "\n")
            else:
                fh.write(",".join(h) + "\n")
        w = csv.writer(fh)
        for row in kept:
            w.writerow(row)
    print(f"Merged {len(curated)} curated Scottish prime outcodes into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
