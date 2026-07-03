"""Build the Halia dashboard for a BigCommerce store (live pull).

Pulls orders from a BigCommerce store's read-only API, scores them with the (unchanged)
engine, and writes output/<store>.html — the same dashboard UI as the Shopify/WooCommerce
paths. The dashboard-first deliverable for a BigCommerce client.

Set up a read-only API account in the control panel (Settings -> API accounts -> Create
API account -> grant Orders + Customers read-only), then:

    BIGCOMMERCE_STORE_HASH=abc12def
    BIGCOMMERCE_ACCESS_TOKEN=xxxx
    python build_bigcommerce.py               # -> output/abc12def.html

Optional: BIGCOMMERCE_MAX_PAGES=2 caps the pull (handy for a first smoke test).
"""
from __future__ import annotations

import json
import os
import re

from build_mvp import dashboard_payload, render_payload
from config import OUTPUT_DIR
from scoring.bigcommerce import bigcommerce_orders_to_customers
from scoring.bigcommerce_fetch import fetch_orders, http_transport
from scoring.combine import HIDDEN_COL, VIC_SPEND_THRESHOLD, score_customers


def store_slug(store_hash: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (store_hash or "").lower()).strip("-") or "store"


def main() -> None:
    from halia import config as _hc  # noqa: F401 — importing loads .env

    store_hash = os.environ.get("BIGCOMMERCE_STORE_HASH")
    if not store_hash or not os.environ.get("BIGCOMMERCE_ACCESS_TOKEN"):
        raise SystemExit(
            "Set BIGCOMMERCE_STORE_HASH and BIGCOMMERCE_ACCESS_TOKEN first "
            "(a read-only BigCommerce API account: Settings -> API accounts)."
        )

    max_pages = int(os.environ.get("BIGCOMMERCE_MAX_PAGES", "0")) or None
    # Cache the raw pull (git-ignored) so we can re-score offline after calibration changes
    # without a fresh pull. BIGCOMMERCE_FROM_CACHE=1 reads it back.
    cache = OUTPUT_DIR / f"bc_orders_{store_slug(store_hash)}.json"
    if os.environ.get("BIGCOMMERCE_FROM_CACHE") and cache.exists():
        orders = json.loads(cache.read_text(encoding="utf-8"))
        print(f"Loaded {len(orders):,} orders from cache ({cache.name})")
    else:
        orders = fetch_orders(http_transport(), max_pages=max_pages)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(orders), encoding="utf-8")

    customers = bigcommerce_orders_to_customers(orders).rename(
        columns={"orders_count": "Count of CUST_ID"}
    )
    scored = score_customers(customers)

    html = render_payload(dashboard_payload(scored, shop=store_hash))
    out = OUTPUT_DIR / f"{store_slug(store_hash)}.html"
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
