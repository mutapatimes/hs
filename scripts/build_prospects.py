"""Turn a pasted stockist directory into a clean, prioritised prospect CSV.

The luxury multi-label directory lists doors as lines like:
    * 10 Corso Como Milan
    * Dover Street Market London London
    * A Ma Manière Washington DC
Each line is "<store name> <city>", where the city is one of a known set of fashion cities. This
splits name from city by matching the LONGEST known city at the end of the line, then maps the city
to a country and a Halia outreach priority (P1 = UK/US where the reference data is deepest, P2 = EU,
P3 = rest). Unknown-city lines are still emitted, flagged for a human to complete.

Stand-alone operator tool. Standard library only.

Usage
-----
    # paste the directory into a text file first (one door per line, leading "*" optional)
    python scripts/build_prospects.py --file ~/Downloads/directory.txt --out output/prospects.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import re

# city -> (country, region_priority). Region: 1 = UK/US, 2 = EU/EEA + CH, 3 = rest.
# Curated from the directory's own cities; extend freely.
_UK = {"London", "Manchester", "Edinburgh", "Glasgow", "Birmingham", "Leeds", "Liverpool",
       "Bristol", "Nottingham", "Newcastle Upon Tyne", "Newcastle", "Aberdeen", "Cambridge",
       "Norwich", "Brighton", "Bath", "Oxford", "Chester", "Harrogate", "Sheffield", "Cardiff",
       "Dublin", "Cork", "Galway", "Limerick", "Belfast", "Southampton"}
_US = {"New York", "Los Angeles", "San Francisco", "Chicago", "Boston", "Dallas", "Houston",
       "Miami", "Atlanta", "Seattle", "Portland", "Denver", "Aspen", "Nashville", "Charleston",
       "Charlotte", "Philadelphia", "Washington DC", "Austin", "San Antonio", "San Diego",
       "Palm Beach", "Santa Fe", "Santa Barbara", "Nantucket", "Las Vegas", "Detroit", "Oakland",
       "Bellevue", "Greenwich", "Scottsdale", "Calabasas", "Malibu", "Newport Beach", "Brooklyn",
       "Manhasset", "Short Hills", "Red Bank", "Milwaukee", "Kansas City", "Tulsa", "Little Rock",
       "Grand Rapids", "Minneapolis", "Edina", "Carmel", "Columbia", "Cincinnati", "Naples",
       "Anchorage", "Honolulu", "Hawaii", "West Hollywood", "Miami Beach", "East Hampton"}
_EU = {"Milan", "Rome", "Florence", "Venice", "Naples", "Turin", "Torino", "Bologna", "Bologne",
       "Paris", "Marseille", "Lyon", "Nice", "Cannes", "Bordeaux", "Toulouse", "Lille", "Strasbourg",
       "Deauville", "Biarritz", "Saint Tropez", "St. Tropez", "Cap Ferret", "Annecy", "Reims",
       "Berlin", "Munich", "München", "Hamburg", "Cologne", "Frankfurt am Main", "Düsseldorf",
       "Stuttgart", "Bonn", "Wiesbaden", "Nürnberg", "Leipzig", "Bielefeld", "Konstanz",
       "Madrid", "Barcelona", "Bilbao", "Valencia", "Palma de Mallorca", "Ibiza", "San Sebastian",
       "Amsterdam", "Rotterdam", "Den Haag", "Utrecht", "Antwerp", "Brussels", "Gent", "Knokke",
       "Hasselt", "Liège", "Copenhagen", "Frederiksberg", "Aarhus", "Odense", "Kolding",
       "Stockholm", "Göteborg", "Gothenburg", "Malmoe", "Oslo", "Bergen", "Stavanger", "Helsinki",
       "Reykjavik", "Zurich", "Geneva", "Basel", "Lugano", "Bern", "Luzern", "Gstaad", "St. Moritz",
       "Sankt Moritz", "Wien", "Salzburg", "Linz", "Graz", "Lisbon", "Porto", "Athens", "Mykonos",
       "Thessaloniki", "Warsaw", "Krakow", "Prague", "Budapest", "Bucharest", "Zagreb", "Sofia",
       "Riga", "Vilnius", "Tallinn", "Luxembourg", "Monaco", "Andorra la Vella"}
# Rest of world (priority 3): a country label so these are clean P3 rows, not "needs review".
_REST = {
    "Japan": ["Tokyo", "Osaka", "Nagoya", "Kyoto", "Fukuoka", "Kobe", "Hyogo", "Sapporo",
              "Hiroshima", "Kanagawa", "Nagano", "Niigata", "Okayama", "Kanazawa", "Gifu",
              "Toyama", "Ishikawa", "Kumamoto", "Shizuoka", "Aichi", "Chiba", "Saitama", "Gunma"],
    "South Korea": ["Seoul", "Busan", "Daegu", "Gangnam-gu", "Gyeonggi"],
    "China": ["Shanghai", "Beijing", "Chengdu", "Hangzhou", "Shenzhen", "Ningbo", "Tianjin",
              "Harbin", "Xi'an", "Wenzhou City"],
    "Hong Kong": ["Hong Kong"], "Taiwan": ["Taipei", "Taichung City", "Tainan City", "Kaohsiung"],
    "Singapore": ["Singapore"], "Thailand": ["Bangkok"], "Australia": ["Sydney", "Melbourne",
              "Brisbane", "Perth", "Adelaide", "Armadale", "Toorak", "Claremont"],
    "New Zealand": ["Auckland", "Wellington", "Christchurch", "Queenstown"],
    "Canada": ["Toronto", "Vancouver", "Montreal", "Calgary", "Edmonton", "Ottawa", "Québec",
               "Halifax", "Hamilton", "Markham"],
    "UAE / Gulf": ["Dubaï", "Abu Dhabi", "Doha", "Kuwait City", "Manama", "Riyadh", "Jeddah",
                   "Khobar", "Beirut", "Salmiya"],
    "Russia / CIS": ["Moscow", "St.Petersburg", "Kiev", "Almaty", "Baku", "Tbilisi", "Astana",
                     "Krasnodar", "Yekaterinburg", "Kharkiv", "Odessa", "Kazan", "Bishkek"],
    "Turkey": ["Istanbul", "Ankara"], "Mexico": ["Mexico D.F."], "Brazil": ["São Paulo",
              "Belo Horizonte", "Brasilia"], "South Africa": ["Cape Town", "Johannesburg"],
    "India": ["Mumbai", "Bangalore", "Hanoi"],
}
_CITY_COUNTRY = {}
for _c in _UK: _CITY_COUNTRY[_c] = ("United Kingdom / Ireland", 1)
for _c in _US: _CITY_COUNTRY[_c] = ("United States", 1)
for _c in _EU: _CITY_COUNTRY[_c] = ("Europe", 2)
for _country, _cs in _REST.items():
    for _c in _cs:
        _CITY_COUNTRY.setdefault(_c, (_country, 3))

# Longest-first so "New York" wins over "York", "Washington DC" over "Washington".
_CITIES_BY_LEN = sorted(_CITY_COUNTRY, key=len, reverse=True)


def parse_line(line: str) -> dict | None:
    """One directory line -> {name, city, country, priority} (priority 3/unknown city -> flagged)."""
    s = line.strip().lstrip("*").strip()
    s = re.sub(r"\s*\*\s*Mini Website\s*$", "", s)          # strip the directory's "* Mini Website"
    s = re.sub(r"\s{2,}", " ", s).strip()
    if not s or len(s) < 3:
        return None
    for city in _CITIES_BY_LEN:
        # city sits at the end of the line, on a word boundary
        if s.endswith(city) and (len(s) == len(city) or s[-len(city) - 1] == " "):
            name = s[: -len(city)].strip(" ,-")
            if not name:
                name = city                                 # a store literally named after its city
            country, prio = _CITY_COUNTRY[city]
            return {"name": name, "city": city, "country": country, "priority": prio}
    # unknown city: keep the whole line as the name, last token as a guessed city, flag it
    toks = s.split()
    return {"name": s, "city": toks[-1] if toks else "", "country": "", "priority": 3}


def build(lines) -> list[dict]:
    seen, out = set(), []
    for ln in lines:
        row = parse_line(ln)
        if not row:
            continue
        key = (row["name"].lower(), row["city"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r: (r["priority"], r["country"], r["name"].lower()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a prioritised prospect CSV from a stockist directory.")
    ap.add_argument("--file", type=Path, required=True, help="Text file: one door per line.")
    ap.add_argument("--out", type=Path, default=Path("output/prospects.csv"))
    ap.add_argument("--focus-west", action="store_true",
                    help="Keep only UK/US/EU doors (drop P3 rest-of-world).")
    args = ap.parse_args()

    rows = build(args.file.read_text(encoding="utf-8").splitlines())
    if args.focus_west:
        rows = [r for r in rows if r["priority"] in (1, 2)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["priority", "name", "city", "country", "status", "contact_name", "email", "notes"])
        for r in rows:
            w.writerow([f"P{r['priority']}", r["name"], r["city"], r["country"], "", "", "", ""])
    p1 = sum(1 for r in rows if r["priority"] == 1)
    p2 = sum(1 for r in rows if r["priority"] == 2)
    unknown = sum(1 for r in rows if r["priority"] == 3)
    print(f"Wrote {len(rows)} prospects to {args.out} "
          f"(P1 UK/US {p1}, P2 EU {p2}, P3/needs-review {unknown}).")


if __name__ == "__main__":
    main()
