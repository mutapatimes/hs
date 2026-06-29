"""Build the Halia dashboard for a WooCommerce store (live pull).

Pulls orders from a WooCommerce store's read-only REST API, scores them with the
(unchanged) engine, and writes output/<store>.html — the same dashboard UI as the
Shopify path. This is the dashboard-first deliverable for a WooCommerce client.

Set up a read-only key in the store's WP admin (WooCommerce -> Settings -> Advanced
-> REST API -> Add key -> permission Read), then:

    WOO_STORE_URL=https://glennorah.co.uk
    WOO_CONSUMER_KEY=ck_xxx
    WOO_CONSUMER_SECRET=cs_xxx
    python build_woo.py                 # -> output/glennorah-co-uk.html

Optional: WOO_MAX_PAGES=2 caps the pull (handy for a first smoke test).
"""
from __future__ import annotations

import json
import os
import re

from build_mvp import dashboard_payload, render_payload
from config import OUTPUT_DIR
from scoring.combine import HIDDEN_COL, VIC_SPEND_THRESHOLD, score_customers
from scoring.woocommerce import woo_orders_to_customers
from scoring.woocommerce_fetch import fetch_orders, http_transport


def store_slug(url: str) -> str:
    bare = re.sub(r"^https?://", "", url.lower()).strip("/")
    return re.sub(r"[^a-z0-9]+", "-", bare).strip("-") or "store"


def main() -> None:
    from halia import config as _hc  # noqa: F401 — importing loads .env

    store = os.environ.get("WOO_STORE_URL")
    if not store or not os.environ.get("WOO_CONSUMER_KEY"):
        raise SystemExit(
            "Set WOO_STORE_URL, WOO_CONSUMER_KEY, WOO_CONSUMER_SECRET first "
            "(a read-only WooCommerce REST API key: ck_… / cs_…)."
        )

    max_pages = int(os.environ.get("WOO_MAX_PAGES", "0")) or None
    # Cache the raw pull (git-ignored) so we can re-score offline after calibration
    # changes without a fresh 20-minute pull. WOO_FROM_CACHE=1 reads it back.
    cache = OUTPUT_DIR / f"woo_orders_{store_slug(store)}.json"
    if os.environ.get("WOO_FROM_CACHE") and cache.exists():
        orders = json.loads(cache.read_text(encoding="utf-8"))
        print(f"Loaded {len(orders):,} orders from cache ({cache.name})")
    else:
        orders = fetch_orders(http_transport(), max_pages=max_pages)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(orders), encoding="utf-8")

    customers = woo_orders_to_customers(orders).rename(
        columns={"orders_count": "Count of CUST_ID"}
    )
    scored = score_customers(customers)

    html = render_payload(dashboard_payload(scored, shop=store))
    out = OUTPUT_DIR / f"{store_slug(store)}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    hidden = int(scored[HIDDEN_COL].sum())
    print(
        f"Pulled {len(orders):,} orders -> {len(scored):,} customers · "
        f"{hidden} hidden VICs (threshold £{VIC_SPEND_THRESHOLD:,.0f})\n"
        f"Wrote {out}  —  open it in a browser."
    )


if __name__ == "__main__":
    main()
