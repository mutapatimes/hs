"""The embedded Shopify app — the Halia dashboard rendered INSIDE admin.shopify.com.

Shopify loads this app's URL in an iframe in the admin, passing a signed session token
(`?id_token=…`). We verify it, token-exchange for the shop's Admin API token, pull +
score that shop's customers, persist them (so the API/fulfilment surfaces have data), and
server-render the same dashboard `build_mvp` produces — with App Bridge added so it's a
valid embedded app, and a per-shop CSP so the admin is allowed to frame it.

Built multi-tenant: every read/write is scoped to the authenticated `shop`.
"""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from halia import config
from halia.api.shopify_auth import (
    ensure_offline_token, require_shop, token_for_request, verify_session_token,
)

_APP_BRIDGE = (
    '<meta name="shopify-api-key" content="{key}">'
    '<script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>'
)

_OPEN_FROM_ADMIN = (
    "<!doctype html><meta charset=utf-8><title>Halia</title>"
    "<body style='font:16px system-ui;padding:48px;color:#1c1b18'>"
    "<h2>Halia</h2><p>Open this app from your Shopify admin "
    "(Apps → Halia) so it can load securely.</p></body>"
)


def _csp(shop: str) -> str:
    return f"frame-ancestors https://{shop} https://admin.shopify.com;"


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
    from halia.engine import engine
    from halia.adapters.shopify_source import ShopifySource

    store.upsert_many(engine.results_from_scored(scored), shop=shop, source="shopify")
    # Reuse the source's order-shaping (order_id -> customer) for the order index.
    src = ShopifySource()
    src._orders = orders  # already fetched; avoid a second pull
    store.upsert_orders(src.iter_orders(), shop=shop)


def register(app, get_store) -> None:
    """Mount the embedded entry + per-shop API routes onto the FastAPI app."""

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        from build_mvp import render_dashboard

        try:
            session_token = token_for_request(request)
            shop = verify_session_token(session_token)
        except Exception:
            return HTMLResponse(_OPEN_FROM_ADMIN)  # not loaded from admin (no valid token)

        token = ensure_offline_token(shop, session_token)
        scored, orders = score_shop(shop, token)
        _persist(get_store(), shop, scored, orders)

        head = _APP_BRIDGE.format(key=config.SHOPIFY_API_KEY or "")
        resp = HTMLResponse(render_dashboard(scored, head_extra=head))
        resp.headers["Content-Security-Policy"] = _csp(shop)
        return resp

    @app.post("/v1/sync")
    def sync_now(request: Request, shop: str = Depends(require_shop)):
        token = ensure_offline_token(shop, token_for_request(request))
        scored, orders = score_shop(shop, token)
        _persist(get_store(), shop, scored, orders)
        return {"shop": shop, "scored": int(len(scored)),
                "hidden_vics": int(scored["hidden_vic"].sum())}

    @app.get("/v1/dashboard")
    def dashboard_data(shop: str = Depends(require_shop)):
        return JSONResponse([r.to_dict() for r in get_store().top_hidden(shop, 200)])
