"""Turn an accessible-luxury DTC brand list into a prioritised Halia prospect CSV.

Accessible-luxury DTC brands (Reformation and its peers) are Halia's sharpest fit: a low price
point on aspirational product means wealthy customers are HIDDEN among students and everyday buyers,
so the capacity-vs-spend gap Halia measures is at its widest. They are also almost all Shopify and
run heavy Meta/IG acquisition, so the install is easy and the Meta-lookalike play lands.

Input: a TSV of `name<TAB>price_low<TAB>price_high<TAB>note` (one brand per line; a "brands like X"
listicle drops straight in). Output: a prospect CSV with a Halia-fit priority.

Priority heuristic (the sweet spot = low entry price + high ceiling + broad reach):
  * entry price <= ~$120 AND ceiling >= ~$600  -> P1 (widest hiding gap, biggest book)
  * a broad ceiling (>= $600) OR a very low entry (<= $60)      -> P2
  * everything else                                             -> P3
Retailers/marketplaces (Anthropologie, & Other Stories) are flagged: different model, softer fit.

Stand-alone operator tool. Standard library only.

Usage
-----
    python scripts/build_brand_prospects.py --file brands.tsv --out output/brand_prospects.csv
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

# Brands that are broad retailers / marketplaces rather than single DTC houses (softer fit: they
# already have scale and their own tooling, and the "hidden VIC" story is diluted across many labels).
_RETAILERS = {"anthropologie", "& other stories", "madewell", "aritzia"}


def _priority(low: float, high: float, name: str) -> tuple[str, str]:
    n = name.strip().lower()
    if n in _RETAILERS:
        return "P3", "broad retailer / marketplace, softer fit"
    if low <= 120 and high >= 600:
        return "P1", "wide entry-to-ceiling gap: wealthy hide among accessible buyers"
    if high >= 600 or low <= 60:
        return "P2", "broad price ceiling or very low entry"
    return "P3", "narrower gap"


def build(rows) -> list[dict]:
    out = []
    for raw in rows:
        parts = [p.strip() for p in raw.rstrip("\n").split("\t")]
        if not parts or not parts[0] or parts[0].startswith("#"):
            continue
        name = parts[0]
        low = float(parts[1]) if len(parts) > 1 and parts[1].replace(".", "").isdigit() else 0.0
        high = float(parts[2]) if len(parts) > 2 and parts[2].replace(".", "").isdigit() else 0.0
        note = parts[3] if len(parts) > 3 else ""
        prio, why = _priority(low, high, name)
        out.append({
            "priority": prio, "name": name,
            "price_low": int(low), "price_high": int(high),
            "fit_reason": why, "note": note,
        })
    order = {"P1": 0, "P2": 1, "P3": 2}
    out.sort(key=lambda r: (order[r["priority"]], -r["price_high"], r["name"].lower()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a Halia prospect CSV from a DTC brand list.")
    ap.add_argument("--file", type=Path, required=True, help="TSV: name<TAB>low<TAB>high<TAB>note")
    ap.add_argument("--out", type=Path, default=Path("output/brand_prospects.csv"))
    args = ap.parse_args()

    rows = build(args.file.read_text(encoding="utf-8").splitlines())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["priority", "brand", "entry_price_usd", "ceiling_price_usd", "halia_fit",
                    "deck", "channel", "status", "contact_name", "email", "notes"])
        for r in rows:
            # every one of these is Shopify-shaped DTC -> the brand deck + App Store route
            w.writerow([r["priority"], r["name"], r["price_low"], r["price_high"], r["fit_reason"],
                        "/present-brands", "Shopify App Store / direct", "", "", "", r["note"]])
    p1 = sum(1 for r in rows if r["priority"] == "P1")
    p2 = sum(1 for r in rows if r["priority"] == "P2")
    print(f"Wrote {len(rows)} brand prospects to {args.out} "
          f"(P1 sweet-spot {p1}, P2 {p2}, P3 {len(rows)-p1-p2}).")


if __name__ == "__main__":
    main()
