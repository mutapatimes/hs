"""Master prospect sheet: every Halia brand prospect, one file, deduplicated and segmented.

Merges the three curated segments into a single sheet with a common schema:
  * accessible-dtc   — Reformation-lane DTC (wealthy hide among accessible buyers)
  * womenswear       — younger modern-feminine independent designers (Philo / NAP / DSM lane)
  * menswear         — contemporary independent menswear (DSM / Comme / NAP lane)

Each brand appears once; when it sits in two segments the more specific designer segment wins.
Priority within a segment: P1 = the sweet spot (indie, core lane / widest hiding gap), P2 = adjacent
or larger indie, P3 = group-owned. Sorted by segment, then priority, then name.

Stand-alone operator tool. Standard library only. Curated sets embedded, so it is reproducible;
run with no args to regenerate the master CSV.

Usage
-----
    python scripts/build_all_prospects.py --out output/prospects_master.csv
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, _HERE / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---- accessible-luxury DTC (Reformation lane) — embedded (name, low, high, note) ----
ACCESSIBLE = [
    ("STAUD", 230, 1700, "LA, ex-Reformation founder; strong IG"),
    ("Posse", 120, 430, "breezy elegance, slow fashion"),
    ("Faithfull The Brand", 30, 389, "Bali-made travel style"),
    ("With Jean", 69, 259, "denim-led, fashion-girl favourite"),
    ("Stone Cold Fox", 104, 1070, "LA vintage-inspired"),
    ("Realisation Par", 79, 295, "cult flattering dresses"),
    ("Rouje", 20, 995, "Jeanne Damas, French muse, huge IG"),
    ("Ciao Lucia", 274, 671, "summery, Riviera/Amalfi"),
    ("Ganni", 274, 671, "Danish, sustainability-forward, big IG"),
    ("Friends with Frank", 59, 699, "Melbourne elevated essentials"),
    ("Jillian Boustred", 110, 600, "Australian, sophisticated eveningwear"),
    ("Roame", 40, 480, "travel-spirit prints"),
    ("Maggie Marilyn", 95, 1495, "NZ, B-Corp, circular"),
    ("Doen", 300, 1200, "Kaia Gerber/Dakota Johnson; prairie-feminine"),
    ("Christy Dawn", 150, 1200, "deadstock/regenerative, own farm"),
    ("Everlane", 40, 500, "radical transparency, minimalist"),
    ("Sezane", 50, 700, "French-girl chic, B-Corp, huge IG"),
    ("Quince", 30, 300, "affordable-luxury direct silk/cashmere"),
    ("ASTR the Label", 60, 350, "flirty feminine occasionwear"),
    ("For Love & Lemons", 85, 600, "romantic lacy, LA"),
    ("FARM Rio", 100, 800, "Brazilian colour/print"),
    ("AMUR", 180, 1300, "NYC sustainable"),
    ("Anthropologie", 20, 1000, "broad retailer / marketplace"),
    ("& Other Stories", 30, 500, "H&M Group"),
    ("Madewell", 25, 400, "denim-led American classic"),
    ("Aritzia", 30, 900, "quietly-luxe basics, large following"),
    ("Reformation", 40, 1000, "the reference: LA, carbon-neutral, cult IG"),
]
_RETAILERS = {"anthropologie", "& other stories", "madewell", "aritzia"}


def _acc_priority(low, high, name):
    if name.lower() in _RETAILERS:
        return "P3"
    if low <= 120 and high >= 600:
        return "P1"
    return "P2" if (high >= 600 or low <= 60) else "P3"


# ---- contemporary independent MENSWEAR (MR PORTER lane) — (name, lane, ownership, note) ----
MENSWEAR = [
    ("Aime Leon Dore", "contemporary", "indie", "NY, huge IG, founder-led"),
    ("A.P.C.", "minimal", "indie", "contemporary French essentials"),
    ("Our Legacy", "contemporary", "indie", "Swedish contemporary, cult"),
    ("Casablanca", "contemporary", "indie", "modern luxe, big IG"),
    ("Fear of God", "contemporary", "indie", "Jerry Lorenzo, independent"),
    ("Fear of God Essentials", "contemporary", "indie", "the accessible line, mass IG"),
    ("AMIRI", "contemporary", "indie", "LA luxe, fast-growing"),
    ("BODE", "contemporary", "indie", "NY cult, storytelling craft"),
    ("Wales Bonner", "contemporary", "indie", "cult modern, cross men/women"),
    ("Willy Chavarria", "contemporary", "indie", "buzzy, culturally sharp"),
    ("Rick Owens", "avant", "indie", "avant cult; a DSM cornerstone"),
    ("Sacai", "contemporary", "indie", "modern Japanese hybrid design"),
    ("JW Anderson", "contemporary", "indie", "buzzy, cross men/women"),
    ("Jacquemus", "contemporary", "indie", "huge indie, men + women"),
    ("Kapital", "craft", "indie", "Japanese craft/denim; DSM lane"),
    ("Visvim", "craft", "indie", "Japanese craft luxe"),
    ("WTAPS", "craft", "indie", "Japanese, Tet"),
    ("Neighborhood", "craft", "indie", "Japanese"),
    ("Human Made", "contemporary", "indie", "NIGO, big IG"),
    ("Needles", "contemporary", "indie", "Nepenthes, Japanese"),
    ("Story mfg.", "craft", "indie", "natural-dye craft, sustainability"),
    ("Enfants Riches Deprimes", "contemporary", "indie", "indie luxe, high price"),
    ("ERL", "contemporary", "indie", "buzzy LA"),
    ("Gallery Dept.", "contemporary", "indie", "LA upcycle/streetwear-luxe"),
    ("NAHMIAS", "contemporary", "indie", "LA luxe"),
    ("Officine Generale", "minimal", "indie", "contemporary French tailoring"),
    ("Drake's", "contemporary", "indie", "contemporary heritage, independent"),
    ("Sunspel", "minimal", "indie", "elevated essentials, independent"),
    ("Stoffa", "minimal", "indie", "made-to-order contemporary"),
    ("Saman Amel", "minimal", "indie", "contemporary tailoring, Stockholm"),
    ("Sease", "contemporary", "indie", "contemporary Italian technical"),
    ("James Perse", "minimal", "indie", "contemporary LA basics"),
    ("Nili Lotan", "contemporary", "indie", "also menswear; NY"),
    ("424", "contemporary", "indie", "LA streetwear-luxe"),
    # adjacent / larger / group
    ("Stone Island", "contemporary", "group", "Moncler-owned techwear, large"),
    ("C.P. Company", "contemporary", "large", "techwear heritage, large"),
    ("Carhartt WIP", "contemporary", "large", "workwear, large"),
    ("Paul Smith", "contemporary", "indie", "British contemporary, large indie"),
    ("Oliver Spencer", "contemporary", "indie", "British contemporary"),
    ("NN07", "minimal", "indie", "Scandi contemporary"),
    ("Orlebar Brown", "resort", "group", "resort/swim, Chanel-owned"),
    ("Frescobol Carioca", "resort", "indie", "resort, founder-led"),
]
_CORE_LANES = {"minimal", "romantic", "contemporary", "craft", "avant"}


def _brand_priority(lane, own):
    if own in ("group", "large"):
        return "P3" if own == "group" else "P2"
    return "P1" if lane in _CORE_LANES else "P2"


def build() -> list[dict]:
    women = _load("build_designer_prospects").BRANDS   # (name, lane, ownership, note)
    rows: list[dict] = []
    # designer segments first (more specific); dedup keeps the first occurrence of a name
    for name, lane, own, note in women:
        rows.append({"segment": "womenswear", "priority": _brand_priority(lane, own),
                     "brand": name.strip(), "detail": lane, "ownership": own,
                     "why_you": "Philo / NAP / DSM credibility in this lane", "note": note})
    for name, lane, own, note in MENSWEAR:
        rows.append({"segment": "menswear", "priority": _brand_priority(lane, own),
                     "brand": name.strip(), "detail": lane, "ownership": own,
                     "why_you": "DSM / Comme / NAP credibility; contemporary menswear", "note": note})
    for name, low, high, note in ACCESSIBLE:
        rows.append({"segment": "accessible-dtc", "priority": _acc_priority(low, high, name),
                     "brand": name.strip(), "detail": f"${low}-${high}", "ownership": "indie",
                     "why_you": "wealthy hide among accessible buyers; Meta-lookalike play", "note": note})
    # dedup by name (first/most-specific wins)
    seen, deduped = set(), []
    for r in rows:
        k = r["brand"].lower().rstrip()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)
    seg_order = {"womenswear": 0, "menswear": 1, "accessible-dtc": 2}
    pri_order = {"P1": 0, "P2": 1, "P3": 2}
    deduped.sort(key=lambda r: (seg_order[r["segment"]], pri_order[r["priority"]], r["brand"].lower()))
    return deduped


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the master prospect sheet.")
    ap.add_argument("--out", type=Path, default=Path("output/prospects_master.csv"))
    args = ap.parse_args()
    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["segment", "priority", "brand", "detail", "ownership", "deck", "channel",
                    "why_you", "status", "contact_name", "email", "notes"])
        for r in rows:
            w.writerow([r["segment"], r["priority"], r["brand"], r["detail"], r["ownership"],
                        "/present-brands", "Shopify / direct intro", r["why_you"],
                        "", "", "", r["note"]])
    from collections import Counter
    by_seg = Counter(r["segment"] for r in rows)
    p1 = sum(1 for r in rows if r["priority"] == "P1")
    print(f"Wrote {len(rows)} prospects to {args.out}  "
          f"(womenswear {by_seg['womenswear']}, menswear {by_seg['menswear']}, "
          f"accessible-dtc {by_seg['accessible-dtc']}; {p1} are P1).")


if __name__ == "__main__":
    main()
