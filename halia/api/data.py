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


def _include_origin(shop: str) -> bool:
    """Origin-proxy signals run only for tenants the operator has opted in (documented
    lawful basis). Off by default for everyone. See scoring.combine.ORIGIN_PROXY_SIGNALS."""
    from halia import config as hcfg
    return shop in hcfg.HALIA_ORIGIN_SIGNAL_SHOPS


def score_shop(shop: str, token: str):
    """Live: fetch + aggregate + score one shop's customers (using its VIC threshold)."""
    from halia.api.settings import settings_for
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers
    from scoring.shopify_fetch import fetch_orders, http_transport

    orders = fetch_orders(http_transport(shop, token))
    customers = orders_to_customers(orders).rename(columns={"orders_count": "Count of CUST_ID"})
    s = settings_for(shop)
    return score_customers(customers, weights=s.get("signal_weights"),
                           vic_threshold=s["vic_threshold"],
                           include_origin=_include_origin(shop)), orders


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
    s = settings_for(shop)
    return score_customers(customers, weights=s.get("signal_weights"),
                           vic_threshold=s["vic_threshold"],
                           include_origin=_include_origin(shop)), orders


def record_activity(shop: str, metric: str, n: int = 1) -> None:
    """Increment a console-dashboard activity counter, swallowing any failure.

    Metrics must NEVER break a real request (a sync, an email, a segment push), so this is
    best-effort: a bad DB or a bad shop key is logged-and-ignored, not raised. See
    ``halia.store.ShopStore.bump_metric`` for the (shop, week, metric) counter model.
    """
    try:
        shop_store().bump_metric(shop, metric, n)
    except Exception:  # pragma: no cover - defensive; counters are non-critical
        pass


def _shopify_carts(shop: str, token: str) -> dict:
    """CUST_ID -> open basket (abandoned checkout), best-effort. Never breaks a sync: a missing
    read_orders scope or any transient error just means no cart panels this run."""
    try:
        from scoring.shopify import carts_by_customer
        from scoring.shopify_fetch import fetch_abandoned_checkouts, http_transport
        return carts_by_customer(fetch_abandoned_checkouts(http_transport(shop, token)))
    except Exception:  # noqa: BLE001 — carts are an enrichment, not load-bearing
        return {}


def _finalize(shop: str, scored, orders: list[dict], carts: dict | None = None) -> dict:
    """Score frame + orders -> RAM cache entry (never persisted). Shared by all sources.

    ``carts`` (CUST_ID -> open basket) is Shopify-only for now; other sources pass None.
    """
    from build_mvp import dashboard_payload
    from halia.api.settings import settings_for
    from halia.engine import engine

    results = engine.results_from_scored(scored)
    s = settings_for(shop)
    benchmarks = {"aov": s["aov"], "max_orders": s["max_orders"], "highest_lt": s["highest_lt"]}
    payload = dashboard_payload(scored, _history(orders), shop, benchmarks, raw_orders=orders,
                                carts_by_customer=carts)
    cache.set(shop, results, payload, _order_index(orders))
    entry = cache.get(shop)

    # Console-dashboard activity: one scan, N customers scanned, M hidden VICs surfaced. Aggregate
    # counters only (no customer data); best-effort so a metrics hiccup never fails the sync.
    hidden_n = sum(1 for r in results if r.flagged and r.hidden_vic)
    record_activity(shop, "scan")
    record_activity(shop, "customers_scanned", len(results))
    record_activity(shop, "hidden_vics", hidden_n)
    return entry


def sync_shop(shop: str, token: str) -> dict:
    """Pull → score → cache in RAM (never persisted). Returns the cache entry."""
    scored, orders = score_shop(shop, token)
    return _finalize(shop, scored, orders, carts=_shopify_carts(shop, token))


def sync_shop_authed(shop: str, session_token: str) -> dict:
    """Sync a Shopify shop, self-healing a revoked/stale offline token.

    Uses the persisted offline token; if the Admin API rejects it (token revoked, app
    reinstalled, or scopes changed), we force a single fresh token exchange from the caller's
    session token and retry once — so a bad stored token repairs itself instead of failing
    every load. Any non-auth failure propagates unchanged.
    """
    from halia.api.shopify_auth import ensure_offline_token
    from scoring.shopify_fetch import ShopifyAuthError

    token = ensure_offline_token(shop, session_token)
    try:
        return sync_shop(shop, token)
    except ShopifyAuthError:
        token = ensure_offline_token(shop, session_token, force=True)
        return sync_shop(shop, token)


def sync_woo(shop: str) -> dict:
    """WooCommerce pull → score → cache in RAM. Returns the cache entry."""
    return _finalize(shop, *score_woo(shop))


def score_bigc(shop: str):
    """Live: pull + score one BigCommerce tenant's customers (using its stored creds)."""
    from halia import config as hcfg
    from halia.api.settings import settings_for
    from scoring.bigcommerce import bigcommerce_to_rest
    from scoring.bigcommerce_fetch import fetch_orders, http_transport
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers

    creds = shop_store().get_bigcommerce(shop)
    if not creds:
        raise RuntimeError("No BigCommerce credentials connected for this tenant")
    transport = http_transport(creds["store_hash"], creds["access_token"])
    orders = [bigcommerce_to_rest(o) for o in fetch_orders(transport, max_pages=hcfg.BIGCOMMERCE_MAX_PAGES)]
    customers = orders_to_customers(orders).rename(columns={"orders_count": "Count of CUST_ID"})
    s = settings_for(shop)
    return score_customers(customers, weights=s.get("signal_weights"),
                           vic_threshold=s["vic_threshold"],
                           include_origin=_include_origin(shop)), orders


def sync_bigc(shop: str) -> dict:
    """BigCommerce pull → score → cache in RAM. Returns the cache entry."""
    return _finalize(shop, *score_bigc(shop))


def score_centra(shop: str):
    """Live: pull + score one Centra tenant's customers (using its stored creds)."""
    from halia import config as hcfg
    from halia.api.settings import settings_for
    from scoring.centra import centra_order_to_rest
    from scoring.centra_fetch import fetch_orders, http_transport
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers

    creds = shop_store().get_centra(shop)
    if not creds:
        raise RuntimeError("No Centra credentials connected for this tenant")
    transport = http_transport(creds["base_url"], creds["api_token"])
    orders = [centra_order_to_rest(o) for o in fetch_orders(transport, max_pages=hcfg.CENTRA_MAX_PAGES)]
    customers = orders_to_customers(orders).rename(columns={"orders_count": "Count of CUST_ID"})
    s = settings_for(shop)
    return score_customers(customers, weights=s.get("signal_weights"),
                           vic_threshold=s["vic_threshold"],
                           include_origin=_include_origin(shop)), orders


def sync_centra(shop: str) -> dict:
    """Centra pull → score → cache in RAM. Returns the cache entry."""
    return _finalize(shop, *score_centra(shop))


def scored_frame_for(shop: str):
    """Re-pull + score this shop's customers, returning the scored DataFrame (flag columns
    + Spent) for calibration. Source-aware like sync_tenant. None if no source is connected.

    Flags (which signals fired) are independent of weights, so calibration is unaffected by
    any weights currently applied — it always measures lift against the canonical base."""
    tenant = shop_store().get_tenant(shop)
    if tenant and tenant["kind"] == "woocommerce":
        return score_woo(shop)[0]
    if tenant and tenant["kind"] == "bigcommerce":
        return score_bigc(shop)[0]
    if tenant and tenant["kind"] == "centra":
        return score_centra(shop)[0]
    token = shop_store().get_token(shop)
    return score_shop(shop, token)[0] if token else None


def sync_tenant(shop: str) -> dict | None:
    """Sync by source: a WooCommerce tenant via stored creds, else Shopify via its token."""
    tenant = shop_store().get_tenant(shop)
    if tenant and tenant["kind"] == "woocommerce":
        return sync_woo(shop)
    if tenant and tenant["kind"] == "bigcommerce":
        return sync_bigc(shop)
    if tenant and tenant["kind"] == "centra":
        return sync_centra(shop)
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


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def score_order(shop: str, payload: dict) -> dict | None:
    """Score the single customer behind one order, in memory. Returns an alert dict, or None.

    Used by the real-time order webhook: nothing is stored, the customer is scored and the
    alert dispatched, then forgotten.
    """
    from halia.api.settings import settings_for
    from scoring.combine import REASONS_COL, SCORE_COL, score_customers
    from scoring.grading import GRADE_LABEL, tier_for, to_score100
    from scoring.shopify import orders_to_customers

    tenant = shop_store().get_tenant(shop)
    kind = tenant["kind"] if tenant else "shopify"
    if kind == "woocommerce":
        from scoring.woocommerce import woo_order_to_rest
        rest = woo_order_to_rest(payload)
    elif kind == "bigcommerce":
        from scoring.bigcommerce import bigcommerce_to_rest
        rest = bigcommerce_to_rest(payload)
    elif kind == "centra":
        from scoring.centra import centra_order_to_rest
        rest = centra_order_to_rest(payload)
    else:
        rest = payload  # Shopify REST order shape
    customers = orders_to_customers([rest]).rename(columns={"orders_count": "Count of CUST_ID"})
    if customers.empty:
        return None
    s = settings_for(shop)
    scored = score_customers(customers, weights=s.get("signal_weights"),
                             vic_threshold=s["vic_threshold"],
                             include_origin=_include_origin(shop))
    row = scored.iloc[0]
    s100 = to_score100(_f(row.get(SCORE_COL)))
    tier = tier_for(s100)
    reasons = str(row.get(REASONS_COL) or "")
    signals = [p.split(":")[0].strip() for p in reasons.split(";") if p.strip()][:3]
    name = (rest.get("billing_address") or {}).get("name") or rest.get("email") or "A client"
    return {"order_id": str(rest.get("id") or ""), "when": rest.get("created_at"),
            "name": name, "grade": GRADE_LABEL.get(tier, tier), "score": s100,
            "signals": signals, "email": rest.get("email"),
            "spend": int(round(_f(rest.get("total_price"))))}


def high_grade_orders(entry: dict, grades=("A*", "A"), limit: int = 30) -> list[dict]:
    """Recent orders placed by surfaced A*/A (hidden-VIC) clients — for live alerts.

    Built from the already-scored cache (payload clients + order index), so nothing extra
    about a customer is stored: it is the same RAM data the dashboard already holds.
    """
    clients = (entry.get("payload") or {}).get("data") or []
    by_cid = {str(c.get("cid")): c for c in clients if c.get("cid")}
    by_email = {(c.get("email") or "").lower(): c for c in clients if c.get("email")}
    gset = set(grades)
    out = []
    for o in entry.get("orders") or []:
        c = by_cid.get(str(o.get("customer_id"))) or by_email.get((o.get("email") or "").lower())
        if not c or c.get("grade") not in gset:
            continue
        out.append({"order_id": o.get("order_id"), "when": o.get("created_at"),
                    "id": c.get("id"), "name": c.get("name"), "grade": c.get("grade"),
                    "score": c.get("score"), "spend": c.get("spend"),
                    "signals": [s.get("d", "").split(":")[0].strip()
                                for s in (c.get("signals") or [])][:3]})
    out.sort(key=lambda a: a["when"] or "", reverse=True)
    return out[:limit]


def recent_orders(entry: dict, limit: int = 100) -> list[dict]:
    rows = [{"order_id": o["order_id"], "created_at": o["created_at"],
             "result": result_by_id(entry, o["customer_id"]) if o["customer_id"] else None}
            for o in entry["orders"]]
    rows.sort(key=lambda x: (_RANK.get(x["result"].tier, 3) if x["result"] else 3,
                             -((x["result"].score or 0) if x["result"] else 0)))
    return rows[:limit]
