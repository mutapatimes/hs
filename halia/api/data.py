"""Shared data access — always via the RAM cache, never a database.

Every surface (the embedded dashboard, the Klaviyo actions, the fulfilment view, the read
APIs) gets a shop's scored customers through here. `results_for(shop)` returns the cached
entry or does a live sync; nothing customer-related is ever persisted. The cache entry holds:
  - `results`  : [ScoreResult]      (all scored customers — for Klaviyo + lookups)
  - `payload`  : dict               (the rendered-dashboard JSON, incl. per-client history)
  - `orders`   : [{order_id, created_at, customer_id, email}]  (for the fulfilment view)
"""
from __future__ import annotations

from halia.api.shopify_auth import shop_store
from halia.cache import cache

_RANK = {"A1": 0, "A": 0, "B": 1, "C": 2}


def score_shop(shop: str, token: str):
    """Live: fetch + aggregate + score one shop's customers (using its VIC threshold)."""
    from halia.api.settings import settings_for
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers
    from scoring.shopify_fetch import fetch_orders, http_transport

    orders = fetch_orders(http_transport(shop, token))
    customers = orders_to_customers(orders).rename(columns={"orders_count": "Count of CUST_ID"})
    threshold = settings_for(shop)["vic_threshold"]
    return score_customers(customers, vic_threshold=threshold), orders


def _history(orders: list[dict]) -> dict:
    """CUST_ID -> [{date, amount, items}], newest first (per-client order history)."""
    by: dict[str, list] = {}
    for o in orders:
        cid = (o.get("customer") or {}).get("id")
        if cid is None:
            continue
        items = sum(int(li.get("quantity") or 0) for li in (o.get("line_items") or []))
        by.setdefault(str(cid), []).append({
            "date": str(o.get("created_at") or "")[:10],
            "amount": round(float(o.get("total_price") or 0), 2), "items": items})
    for rows in by.values():
        rows.sort(key=lambda r: r["date"], reverse=True)
    return by


def _order_index(orders: list[dict]) -> list[dict]:
    out = []
    for o in orders:
        cust = o.get("customer") or {}
        out.append({"order_id": str(o.get("id") or o.get("name")),
                    "created_at": o.get("created_at"),
                    "customer_id": None if cust.get("id") is None else str(cust.get("id")),
                    "email": o.get("email") or cust.get("email")})
    return out


def score_woo(shop: str):
    """Live: pull + score one WooCommerce tenant's customers (using its stored creds)."""
    from halia import config as hcfg
    from halia.api.settings import settings_for
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers
    from scoring.woocommerce import woo_order_to_rest
    from scoring.woocommerce_fetch import fetch_orders, http_transport

    creds = shop_store().get_woocommerce(shop)
    if not creds:
        raise RuntimeError("No WooCommerce credentials connected for this tenant")
    transport = http_transport(creds["store_url"], creds["consumer_key"], creds["consumer_secret"])
    orders = [woo_order_to_rest(o) for o in fetch_orders(transport, max_pages=hcfg.WOO_MAX_PAGES)]
    customers = orders_to_customers(orders).rename(columns={"orders_count": "Count of CUST_ID"})
    threshold = settings_for(shop)["vic_threshold"]
    return score_customers(customers, vic_threshold=threshold), orders


def _finalize(shop: str, scored, orders: list[dict]) -> dict:
    """Score frame + orders -> RAM cache entry (never persisted). Shared by all sources."""
    from build_mvp import dashboard_payload
    from halia.api.settings import settings_for
    from halia.engine import engine

    results = engine.results_from_scored(scored)
    s = settings_for(shop)
    benchmarks = {"aov": s["aov"], "max_orders": s["max_orders"], "highest_lt": s["highest_lt"]}
    payload = dashboard_payload(scored, _history(orders), shop, benchmarks)
    cache.set(shop, results, payload, _order_index(orders))
    return cache.get(shop)


def sync_shop(shop: str, token: str) -> dict:
    """Pull → score → cache in RAM (never persisted). Returns the cache entry."""
    return _finalize(shop, *score_shop(shop, token))


def sync_woo(shop: str) -> dict:
    """WooCommerce pull → score → cache in RAM. Returns the cache entry."""
    return _finalize(shop, *score_woo(shop))


def sync_tenant(shop: str) -> dict | None:
    """Sync by source: a WooCommerce tenant via stored creds, else Shopify via its token."""
    tenant = shop_store().get_tenant(shop)
    if tenant and tenant["kind"] == "woocommerce":
        return sync_woo(shop)
    token = shop_store().get_token(shop)
    return sync_shop(shop, token) if token else None


def results_for(shop: str) -> dict | None:
    """The shop's live entry — from RAM, or a fresh sync using its stored source/creds."""
    return cache.get(shop) or sync_tenant(shop)


# ── helpers over a cache entry ──────────────────────────────────────────────────
def hidden_results(entry: dict, limit: int = 1000) -> list:
    rs = [r for r in entry["results"] if r.flagged and r.hidden_vic]
    rs.sort(key=lambda r: r.score or 0, reverse=True)
    return rs[:limit]


def result_by_id(entry: dict, cid) -> object | None:
    cid = str(cid)
    return next((r for r in entry["results"] if r.customer_id == cid), None)


def result_by_email(entry: dict, email: str) -> object | None:
    em = (email or "").lower()
    matches = [r for r in entry["results"] if (r.email or "").lower() == em]
    return max(matches, key=lambda r: r.score or 0) if matches else None


def score_for_order(entry: dict, order_id: str):
    oid = str(order_id)
    o = next((o for o in entry["orders"] if o["order_id"] == oid), None)
    return result_by_id(entry, o["customer_id"]) if o and o["customer_id"] else None


def recent_orders(entry: dict, limit: int = 100) -> list[dict]:
    rows = [{"order_id": o["order_id"], "created_at": o["created_at"],
             "result": result_by_id(entry, o["customer_id"]) if o["customer_id"] else None}
            for o in entry["orders"]]
    rows.sort(key=lambda x: (_RANK.get(x["result"].tier, 3) if x["result"] else 3,
                             -((x["result"].score or 0) if x["result"] else 0)))
    return rows[:limit]
