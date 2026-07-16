"""Detect which prospect brands run on Shopify (so you know the install experience to promise).

For each domain: try /products.json (a Shopify tell), then fall back to homepage + header markers.
Classifies the e-commerce platform and whether Halia can connect it today:
  shopify / woocommerce / bigcommerce  -> connectable
  salesforce (SFCC) / bespoke / unknown -> not yet / needs a custom path

Input: a CSV or text file with a ``domain`` column (or ``brand,domain`` lines). Output: the same
rows plus ``platform`` and ``halia_connect``. Polite: one or two GETs per domain, short timeout,
a normal User-Agent. Domains you feed it should be verified; a wrong domain reads as unknown.

Usage
-----
    python scripts/check_shopify.py --file brand_domains.csv --out output/platforms.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.request

_UA = "Mozilla/5.0 (compatible; HaliaProspectCheck/1.0; +https://haliascore.com)"
_TIMEOUT = 12
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE   # some prospect sites have odd certs; we only read public HTML

_CONNECTABLE = {"shopify", "woocommerce", "bigcommerce"}


def _norm(domain: str) -> str:
    d = domain.strip().lower().rstrip("/")
    d = d.split("//")[-1].split("/")[0]
    return d


def _get(url: str, want_json: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_CTX) as r:
            body = r.read(200_000).decode("utf-8", "replace")
            return r.status, dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), ""
    except Exception:  # noqa: BLE001 — DNS fail, timeout, refused: treat as unreachable
        return None, {}, ""


def _shopify_markers(headers: dict, body: str) -> bool:
    """Shopify tells, including headless/Hydrogen ones (the analytics beacon + cookies survive
    even when the storefront is custom-rendered and /products.json is disabled)."""
    hl = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
    b = body.lower()
    return (
        any(m in hl for m in ("x-shopify", "x-shopid", "x-sorting-hat-shopid", "_shopify_y", "_shopify_s"))
        or any(m in b for m in (
            "cdn.shopify.com", "cdn.shopifycdn", "cdn/shop/", "shopify.theme", "myshopify.com",
            "window.shopify", "shopifycloud", "monorail-edge.shopifysvc", "shopify-features",
            "/cdn/shopifycloud/"))
    )


def detect(domain: str) -> str:
    d = _norm(domain)
    if not d:
        return "unknown"
    base = f"https://{d}"
    # 1) products.json / cart.js — near-definitive Shopify tells (unless disabled)
    st, _h, body = _get(f"{base}/products.json?limit=1", want_json=True)
    if st == 200 and body.lstrip().startswith("{"):
        try:
            if "products" in json.loads(body):
                return "shopify"
        except Exception:  # noqa: BLE001
            pass
    # 2) homepage markers (headers + HTML), retrying www. once if unreachable (bot walls / DNS)
    st, headers, body = _get(base)
    if st is None:
        st, headers, body = _get(f"https://www.{d}")
    if _shopify_markers(headers, body):
        return "shopify"
    b = body.lower()
    hl = " ".join(f"{k}:{v}" for k, v in headers.items()).lower()
    if "demandware.static" in b or "dwsecuretoken" in hl or "/on/demandware" in b or "demandware.edgesuite" in b:
        return "salesforce"                         # SFCC — not connectable yet
    if "wp-content/plugins/woocommerce" in b or "woocommerce.js" in b or "wc-ajax" in b:
        return "woocommerce"
    if "cdn11.bigcommerce.com" in b or "bigcommerce.com/s-" in b:
        return "bigcommerce"
    if st is None:
        return "unreachable"
    return "bespoke"                                # renders, but none of the known platform tells


def main() -> None:
    ap = argparse.ArgumentParser(description="Detect prospect e-commerce platforms.")
    ap.add_argument("--file", type=Path, required=True, help="CSV/txt with a domain (or brand,domain) column")
    ap.add_argument("--out", type=Path, default=Path("output/platforms.csv"))
    args = ap.parse_args()

    raw = args.file.read_text(encoding="utf-8").splitlines()
    reader = csv.DictReader(raw)
    has_cols = reader.fieldnames and "domain" in [c.strip().lower() for c in reader.fieldnames]
    rows = []
    if has_cols:
        for r in reader:
            rows.append({k.strip().lower(): v for k, v in r.items()})
    else:
        for line in raw:                            # "brand,domain" or bare "domain"
            parts = [p.strip() for p in line.split(",")]
            if not parts or not parts[-1] or parts[-1].lower() == "domain":
                continue
            rows.append({"brand": parts[0] if len(parts) > 1 else "", "domain": parts[-1]})

    out = []
    for r in rows:
        plat = detect(r.get("domain", ""))
        connect = "yes" if plat in _CONNECTABLE else ("custom/no" if plat in ("salesforce", "bespoke") else plat)
        out.append({**r, "platform": plat, "halia_connect": connect})
        print(f"  {r.get('brand',''):22} {r.get('domain',''):28} -> {plat}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["brand", "domain", "platform", "halia_connect"]
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    c = Counter(r["platform"] for r in out)
    print(f"\nWrote {len(out)} to {args.out}  ({dict(c)})")


if __name__ == "__main__":
    main()
