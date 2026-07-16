"""Curated prospect list: younger, modern, feminine, INDEPENDENT luxury womenswear brands.

Filtered from the NET-A-PORTER designer roster to the lane a founder with Phoebe Philo /
NET-A-PORTER / Dover Street Market experience can pitch with real credibility: contemporary,
founder-led women's ready-to-wear where wealthy clients hide among aspirational buyers, the brand
is DTC + wholesale with an IG-driven book, and there is a marketing team but no dedicated
clienteling / personal-shopping function. Halia gives them VIP treatment without that headcount.

Deliberately EXCLUDED: conglomerate mega-houses (Gucci, Dior, Saint Laurent, Prada, Chanel...) that
run their own clienteling; jewelry / eyewear / homeware / fragrance sublabels; menswear-led labels;
footwear/swim-only; and heritage giants (Loro Piana, Brunello Cucinelli). Those have their own
tooling or the wrong customer shape.

Priority:
  P1 = independent, founder-led, core feminine lane (modern-minimal / romantic / contemporary-DTC)
  P2 = independent but adjacent lane (resort / occasion-led), or a larger independent
  P3 = conglomerate-owned or very large (kept for awareness; softer fit)

Lanes: minimal (the Philo lane), romantic, contemporary, resort, occasion.

Stand-alone operator tool. Standard library only. The curated set is embedded so it is
reproducible and extendable; run with no args to regenerate the CSV.

Usage
-----
    python scripts/build_designer_prospects.py --out output/designer_prospects.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

# (brand, lane, ownership: indie|group|large, note — the pitch hook where relevant)
BRANDS = [
    # --- the Philo lane: modern minimal, founder-led (your sharpest credibility) ---
    ("Toteme", "minimal", "indie", "Scandi minimalism, huge IG; the modern-Philo lane"),
    ("TOVE", "minimal", "indie", "founded by ex-Toteme team; considered modern womenswear"),
    ("Khaite", "minimal", "indie", "Cate Holstein, NY; modern feminine luxury, fast-growing"),
    ("Gabriela Hearst", "minimal", "indie", "sustainable modern luxury; founder now also at Chloe"),
    ("The Row", "minimal", "large", "Olsen; pure quiet-luxury Philo lane but large + private"),
    ("Studio Nicholson", "minimal", "indie", "considered minimal; contemporary"),
    ("FFORME", "minimal", "indie", "modern considered womenswear, NY"),
    ("Another Tomorrow", "minimal", "indie", "sustainable modern, traceable"),
    ("Maria McManus", "minimal", "indie", "sustainable modern minimal, NY"),
    ("Co", "minimal", "indie", "modern feminine, LA"),
    ("ST. AGNI", "minimal", "indie", "Australian minimal, DTC-strong"),
    ("Matteau", "resort", "indie", "Australian minimal swim + rtw"),
    ("Deiji Studios", "minimal", "indie", "Australian loungewear/minimal, IG-led"),
    ("Anine Bing", "contemporary", "indie", "founder-led DTC, very large IG, LA"),
    ("Nili Lotan", "contemporary", "indie", "NY contemporary, founder-led"),
    ("SLVRLAKE", "contemporary", "indie", "elevated denim, founder-led"),
    ("The Frankie Shop", "contemporary", "indie", "contemporary, cult IG, Paris/NY"),
    ("Tibi", "contemporary", "indie", "Amy Smilovic, modern creative-pragmatism, strong community"),
    ("TWP", "contemporary", "indie", "modern womenswear (Trish Wescoat Pound)"),
    ("KALLMEYER", "contemporary", "indie", "NY tailoring-led contemporary, founder-led"),
    ("Maryam Nassir Zadeh", "contemporary", "indie", "NY downtown cult, founder-led"),

    # --- romantic / feminine, founder-led ---
    ("Cecilie Bahnsen", "romantic", "indie", "Danish romantic-feminine; Philo-adjacent aesthetic"),
    ("Simone Rocha", "romantic", "indie", "founder-led romantic-feminine, London"),
    ("Ulla Johnson", "romantic", "indie", "feminine, founder-led, DTC-strong"),
    ("Magda Butrym", "romantic", "indie", "Polish feminine, founder-led"),
    ("Emilia Wickstead", "occasion", "indie", "feminine occasion, London, founder-led"),
    ("Roksanda", "romantic", "indie", "colour-led feminine, London"),
    ("Rosie Assoulin", "romantic", "indie", "modern feminine, NY, founder-led"),
    ("Bernadette", "romantic", "indie", "mother-daughter, painterly feminine"),
    ("Borgo de Nor", "romantic", "indie", "print-led feminine, London"),
    ("La DoubleJ", "romantic", "indie", "JJ Martin, maximalist print feminine, Milan"),
    ("Saloni", "romantic", "indie", "print feminine, London, founder-led"),
    ("Sea", "contemporary", "indie", "NY feminine, founder-led"),
    ("RIXO", "romantic", "indie", "print feminine, London, DTC + IG"),
    ("Johanna Ortiz", "resort", "indie", "Colombian feminine, founder-led"),
    ("Cara Cara", "resort", "indie", "NY feminine prints, founder-led"),
    ("La Ligne", "contemporary", "indie", "stripes/knits, NY, founder-led"),
    ("LESET", "contemporary", "indie", "elevated knit basics, LA, IG-led"),
    ("Diotima", "contemporary", "indie", "Rachel Scott, modern; CFDA-recognised"),
    ("Wiederhoeft", "occasion", "indie", "romantic occasion, NY"),

    # --- feminine occasion / resort (adjacent lane) ---
    ("Alessandra Rich", "occasion", "indie", "glam feminine occasion"),
    ("Self-Portrait", "occasion", "indie", "Han Chong; accessible-luxe feminine occasion, big"),
    ("Solace London", "occasion", "indie", "contemporary occasion"),
    ("Rebecca Vallance", "occasion", "indie", "Australian feminine occasion"),
    ("Alex Perry", "occasion", "indie", "Australian glam"),
    ("Maticevski", "occasion", "indie", "Australian sculptural"),
    ("Aje", "resort", "indie", "Australian feminine, DTC-strong"),
    ("ALEMAIS", "resort", "indie", "Australian print, sustainability-forward"),
    ("Costarellos", "occasion", "indie", "Greek feminine occasion"),

    # --- larger / group-owned modern-feminine (awareness; softer, they have teams) ---
    ("Chloe", "romantic", "group", "Richemont; Philo history makes it credibility-relevant"),
    ("Ganni", "contemporary", "large", "Danish, part-PE-owned, very large IG"),
    ("Zimmermann", "resort", "large", "Australian, large, private-equity backed"),
    ("Ulla Johnson ", "romantic", "indie", ""),  # dedup guard example (trailing space) — dropped
    ("Proenza Schouler", "minimal", "indie", "NY, independent, modern"),
    ("Altuzarra", "contemporary", "indie", "NY/Paris modern feminine"),
    ("Patou", "romantic", "group", "LVMH; young modern-feminine relaunch"),
    ("Marni", "contemporary", "group", "OTB; creative womenswear"),
]

_CORE_LANES = {"minimal", "romantic", "contemporary"}


def _priority(lane: str, ownership: str) -> str:
    if ownership in ("group", "large"):
        return "P3" if ownership == "group" else "P2"
    return "P1" if lane in _CORE_LANES else "P2"          # indie core lane = sharpest fit


def build(brands=BRANDS) -> list[dict]:
    seen, out = set(), []
    for name, lane, own, note in brands:
        key = name.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"priority": _priority(lane, own), "brand": name.strip(),
                    "lane": lane, "ownership": own, "note": note})
    order = {"P1": 0, "P2": 1, "P3": 2}
    out.sort(key=lambda r: (order[r["priority"]], r["lane"], r["brand"].lower()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Curated modern-feminine womenswear prospect CSV.")
    ap.add_argument("--out", type=Path, default=Path("output/designer_prospects.csv"))
    args = ap.parse_args()
    rows = build()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["priority", "brand", "aesthetic_lane", "ownership", "deck", "channel",
                    "why_you", "status", "contact_name", "email", "notes"])
        for r in rows:
            w.writerow([r["priority"], r["brand"], r["lane"], r["ownership"], "/present-brands",
                        "Shopify / direct intro", "Philo / NAP / DSM credibility in this exact lane",
                        "", "", "", r["note"]])
    p1 = sum(1 for r in rows if r["priority"] == "P1")
    p2 = sum(1 for r in rows if r["priority"] == "P2")
    print(f"Wrote {len(rows)} designer prospects to {args.out} "
          f"(P1 indie core-lane {p1}, P2 {p2}, P3 group {len(rows)-p1-p2}).")


if __name__ == "__main__":
    main()
