"""The embedded Shopify app — the Halia dashboard rendered INSIDE admin.shopify.com.

Shopify loads this app's URL in an iframe in the admin, passing a signed session token
(`?id_token=…`). We verify it and:
  - on the FIRST load for a shop, token-exchange + pull + score + persist its customers;
  - on every load, render the dashboard from the STORED payload (instant, no live fetch),
    with a "Refresh scores" button that re-syncs on demand.

Rendering from a stored payload (rather than re-scoring on every page view) is what makes
the page fast and robust — a transient Shopify hiccup can't blank the dashboard. Every
read/write is scoped to the authenticated `shop` (multi-tenant). App Bridge is injected so
it's a valid embedded app, plus a per-shop CSP so the admin is allowed to frame it.
"""
from __future__ import annotations

import json
import traceback

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from halia import config
from halia.api.shopify_auth import (
    ensure_offline_token, require_shop, token_for_request, verify_session_token,
)

_HEAD = (
    '<meta name="shopify-api-key" content="{key}">'
    '<script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>'
    # Hide the template's simulated Shopify shell (it predates real embedding).
    "<style>.topbar,.sidenav,.crumb{{display:none!important}}"
    ".admin{{display:block!important}}.canvas{{min-height:100vh;padding-top:18px}}"
    "#halia-refresh{{position:fixed;top:14px;right:18px;z-index:200;padding:8px 14px;"
    "border-radius:8px;border:1px solid #d8c79a;background:#1f564a;color:#fff;"
    "font:600 13px system-ui;cursor:pointer}}#halia-refresh[disabled]{{opacity:.6}}</style>"
    # Refresh button — App Bridge attaches the session token to the fetch automatically.
    "<script>addEventListener('DOMContentLoaded',function(){{"
    "var b=document.createElement('button');b.id='halia-refresh';"
    "b.textContent='\\u21bb Refresh scores';b.onclick=function(){{"
    "b.disabled=true;b.textContent='Refreshing\\u2026';"
    "fetch('/v1/sync',{{method:'POST'}}).then(function(r){{return r.json()}})"
    ".then(function(){{location.reload()}})"
    ".catch(function(){{b.textContent='Refresh failed';b.disabled=false}})}};"
    "document.body.appendChild(b)}});</script>"
)

_OPEN_FROM_ADMIN = (
    "<!doctype html><meta charset=utf-8><title>Halia</title>"
    "<body style='font:16px system-ui;padding:48px;color:#1c1b18'>"
    "<h2>Halia</h2><p>Open this app from your Shopify admin (Apps → Halia) "
    "so it can load securely.</p></body>"
)


def _csp(shop: str) -> str:
    return f"frame-ancestors https://{shop} https://admin.shopify.com;"


def _head() -> str:
    return _HEAD.format(key=config.SHOPIFY_API_KEY or "")


def _error_page(head: str, detail: str) -> str:
    return (
        "<!doctype html><html><head>" + head + "</head>"
        "<body style='font:15px system-ui;padding:40px;color:#1c1b18'>"
        "<h2>Couldn't load your scores</h2>"
        "<p style='color:#6b675e;max-width:540px'>Halia hit a snag fetching from Shopify. "
        "This is usually transient — hit <b>Refresh scores</b> (top right) to try again.</p>"
        f"<pre style='background:#f4f2ec;padding:12px;border-radius:8px;color:#8a5;"
        f"font-size:12px;overflow:auto'>{detail[:300]}</pre></body></html>"
    )


def score_shop(shop: str, token: str):
    """Fetch + aggregate + score one shop's customers. Returns (scored_df, orders)."""
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers
    from scoring.shopify_fetch import fetch_orders, http_transport

    orders = fetch_orders(http_transport(shop, token))
    customers = orders_to_customers(orders).rename(columns={"orders_count": "Count of CUST_ID"})
    return score_customers(customers), orders


def _persist(store, shop: str, scored, orders) -> None:
    """Store the shop's scored customers + order index (for the API/fulfilment surfaces)."""
    from halia.adapters.shopify_source import ShopifySource
    from halia.engine import engine

    store.upsert_many(engine.results_from_scored(scored), shop=shop, source="shopify")
    src = ShopifySource()
    src._orders = orders  # already fetched; avoid a second pull
    store.upsert_orders(src.iter_orders(), shop=shop)


def _sync_and_store(store, shop: str, token: str) -> dict:
    """Live pull → score → persist scores/orders AND the prerendered dashboard payload."""
    from build_mvp import dashboard_payload

    scored, orders = score_shop(shop, token)
    _persist(store, shop, scored, orders)
    payload = dashboard_payload(scored)
    store.save_dashboard(shop, json.dumps(payload))
    return payload


def register(app, get_store) -> None:
    """Mount the embedded entry + per-shop API routes onto the FastAPI app."""

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        from build_mvp import render_payload

        try:
            session_token = token_for_request(request)
            shop = verify_session_token(session_token)
        except Exception:
            return HTMLResponse(_OPEN_FROM_ADMIN)  # not loaded from admin (no valid token)

        head = _head()
        try:
            store = get_store()
            payload_json = store.get_dashboard(shop)
            if payload_json:
                payload = json.loads(payload_json)  # instant: render stored data
            else:
                token = ensure_offline_token(shop, session_token)  # first load → live sync
                payload = _sync_and_store(store, shop, token)
            body = render_payload(payload, head_extra=head)
        except Exception as exc:
            traceback.print_exc()  # surfaces in Render logs
            body = _error_page(head, f"{type(exc).__name__}: {exc}")

        resp = HTMLResponse(body)
        resp.headers["Content-Security-Policy"] = _csp(shop)
        return resp

    @app.post("/v1/sync")
    def sync_now(request: Request, shop: str = Depends(require_shop)):
        token = ensure_offline_token(shop, token_for_request(request))
        payload = _sync_and_store(get_store(), shop, token)
        return {"shop": shop, "hidden_vics": len(payload["data"])}

    @app.get("/v1/dashboard")
    def dashboard_data(shop: str = Depends(require_shop)):
        return JSONResponse([r.to_dict() for r in get_store().top_hidden(shop, 200)])
