"""Build the dashboard's world-map geometry (web/world_map.json) from open data.

Two public-domain sources, ingested OFFLINE (never a live API), like every reference build:

  1. Natural Earth 50m land  ne_50m_land.geojson  (naturalearthdata.com, public domain)
        -> simplified land outlines the map draws. Rings are filtered (tiny islands dropped,
           Antarctica dropped), Douglas-Peucker simplified (finer tolerance around Europe, where
           the first merchants are), and quantized to 2 dp.
  2. Census ZCTA Gazetteer   20xx_Gaz_zcta_national.zip  (census.gov, public domain)
        -> a mean lat/lng centroid per 3-digit US ZIP prefix (~900 rows), which the map uses to
           place US client bubbles (the UK bubbles use the postcode-area centroids already in the
           template). ZIP3 keeps the table compact and matches the map's metro-level grain.

The output (web/world_map.json) is committed: pure geometry, no PII. build_mvp injects it into the
dashboard at render time as __WORLD__.

Stand-alone operator tool (NOT imported by the app or tests). Standard library only.

Usage
-----
    python scripts/build_world_map.py --land ne_50m_land.geojson --zcta 2025_Gaz_zcta_national.zip
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import ROOT  # noqa: E402

OUT_FILE = ROOT / "web" / "world_map.json"

_LAT_MIN = -56.0          # drop Antarctica; the map's usable band
_MIN_RING_SPAN = 1.0      # drop rings whose bbox area (sq degrees) is below this (tiny islands)
_EUROPE = (34.0, 63.0, -12.0, 32.0)   # lat_min, lat_max, lng_min, lng_max — keep finer detail here
_TOL_EUROPE = 0.05        # RDP tolerance (degrees) inside the Europe box
_TOL_WORLD = 0.18         # elsewhere


def _rdp(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Iterative Douglas-Peucker (recursion-free: some rings are long)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        far_i, far_d = -1, tol
        for i in range(a + 1, b):
            px, py = points[i]
            # Degenerate baseline (a closed ring's first == last point): fall back to the
            # distance from the endpoint, else every interior point measures ~0 and vanishes.
            d = (abs(dx * (ay - py) - dy * (ax - px)) / norm) if norm > 1e-9 \
                else math.hypot(px - ax, py - ay)
            if d > far_d:
                far_i, far_d = i, d
        if far_i > 0:
            keep[far_i] = True
            stack.append((a, far_i))
            stack.append((far_i, b))
    return [p for p, k in zip(points, keep) if k]


def _in_europe(ring: list[tuple[float, float]]) -> bool:
    lat_min, lat_max, lng_min, lng_max = _EUROPE
    return any(lat_min <= la <= lat_max and lng_min <= ln <= lng_max for la, ln in ring)


def build_outlines(geojson: dict) -> list[list[list[float]]]:
    """GeoJSON land -> simplified [[lat,lng], ...] rings (exterior rings only)."""
    rings: list[list[tuple[float, float]]] = []
    for feat in geojson.get("features", []):
        geom = feat.get("geometry") or {}
        polys = geom.get("coordinates") or []
        if geom.get("type") == "Polygon":
            polys = [polys]
        for poly in polys:
            if not poly:
                continue
            ring = [(la, ln) for ln, la in poly[0]]        # exterior ring; GeoJSON is [lng,lat]
            lats = [p[0] for p in ring]
            lngs = [p[1] for p in ring]
            if max(lats) < _LAT_MIN:                       # Antarctica
                continue
            span = (max(lats) - min(lats)) * (max(lngs) - min(lngs))
            if span < _MIN_RING_SPAN and not _in_europe(ring):
                continue
            tol = _TOL_EUROPE if _in_europe(ring) else _TOL_WORLD
            simple = _rdp(ring, tol)
            if len(simple) >= 4:
                rings.append(simple)
    return [[[round(la, 2), round(ln, 2)] for la, ln in r] for r in rings]


def build_us3(zcta_zip: Path) -> dict[str, list[float]]:
    """Census gazetteer zip -> {zip3: [mean_lat, mean_lng]} over its ZCTAs."""
    acc: dict[str, list[float]] = {}
    with zipfile.ZipFile(zcta_zip) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        header = zf.read(name).split(b"\n", 1)[0].decode("utf-8-sig")
        delim = "|" if "|" in header else "\t"          # Census switched tab -> pipe in 2025
        with zf.open(name) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"), delimiter=delim)
            fields = {k.strip(): k for k in (reader.fieldnames or [])}
            geoid, lat_c, lng_c = fields["GEOID"], fields["INTPTLAT"], fields["INTPTLONG"]
            for row in reader:
                z = str(row[geoid]).strip()
                if len(z) != 5 or not z.isdigit():
                    continue
                try:
                    la, ln = float(row[lat_c]), float(row[lng_c])
                except (TypeError, ValueError):
                    continue
                cell = acc.setdefault(z[:3], [0.0, 0.0, 0])
                cell[0] += la
                cell[1] += ln
                cell[2] += 1
    return {k: [round(v[0] / v[2], 2), round(v[1] / v[2], 2)] for k, v in sorted(acc.items())}


def main() -> None:
    ap = argparse.ArgumentParser(description="Build web/world_map.json from Natural Earth + Census data.")
    ap.add_argument("--land", type=Path, required=True, help="ne_50m_land.geojson (Natural Earth)")
    ap.add_argument("--zcta", type=Path, required=True, help="20xx_Gaz_zcta_national.zip (Census)")
    ap.add_argument("--out", type=Path, default=OUT_FILE)
    args = ap.parse_args()

    outlines = build_outlines(json.loads(args.land.read_text(encoding="utf-8")))
    us3 = build_us3(args.zcta)
    doc = {"outlines": outlines, "us3": us3}
    args.out.write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    pts = sum(len(r) for r in outlines)
    print(f"Wrote {args.out}: {len(outlines)} land rings ({pts:,} points), "
          f"{len(us3)} US ZIP3 centroids, {args.out.stat().st_size / 1024:.0f} KB.")


if __name__ == "__main__":
    main()
