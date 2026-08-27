"""The embedded Shopify app — the Halia dashboard rendered INSIDE admin.shopify.com.

Shopify loads this app's URL in an iframe, passing a signed session token (`?id_token=…`).
We verify it, token-exchange for the shop's Admin token, and render the dashboard from the
**RAM cache** (`halia.cache` via `halia.api.data`) — scoring live on a cache miss. No
customer data is ever written to a database: it lives in memory for a few minutes, then is
gone. App Bridge is injected (valid embedded app) plus a per-shop CSP so the admin can frame it.
"""
from __future__ import annotations

import traceback

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from halia import config
from halia.api import data
from halia.api.shopify_auth import (
    require_shop, token_for_request, verify_session_token,
)
from halia.cache import cache

_HEAD = (
    '<meta name="shopify-api-key" content="{key}">'
    '<script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>'
    "<style>.topbar,.sidenav,.crumb{{display:none!important}}"
    ".admin{{display:block!important}}.canvas{{min-height:100vh;padding-top:18px}}"
    "#halia-refresh{{position:fixed;top:14px;right:18px;z-index:55;padding:8px 14px;"
    "border-radius:0;border:1px solid #d8c79a;background:#1f564a;color:#fff;"
    "font:600 13px system-ui;cursor:pointer}}#halia-refresh[disabled]{{opacity:.6}}"
    "body:has(.drawer.show) #halia-refresh{{display:none}}</style>"
    "<script>addEventListener('DOMContentLoaded',function(){{"
    "var b=document.createElement('button');b.id='halia-refresh';"
    "b.textContent='\\u21bb Refresh scores';b.onclick=function(){{"
    "b.disabled=true;b.textContent='Refreshing\\u2026';"
    "fetch('/v1/sync',{{method:'POST'}}).then(function(r){{return r.json()}})"
    ".then(function(){{location.reload()}})"
    ".catch(function(){{b.textContent='Refresh failed';b.disabled=false}})}};"
    "document.body.appendChild(b)}});</script>"
)

# App Bridge admin sidebar nav. The app name (rendered by Shopify) links home -> "/" (Overview),
# so the home link is present only to satisfy App Bridge and is hidden from the menu. Each item
# uses a DISTINCT path (/app/<section>) — App Bridge highlights the active item by pathname, so
# query-string-only links (all "/") can't be told apart and the highlight sticks. The dashboard
# maps the path to a view on load and keeps it in step. Order = by importance; labels are short
# nouns matching the in-app tab titles.
_NAV_MENU = (
    "<ui-nav-menu>"
    '<a href="/" rel="home">Halia</a>'
    '<a href="/view/clients">Clients</a>'
    '<a href="/view/catalogues">Catalogues</a>'
    '<a href="/view/pipeline">Pipeline</a>'
    '<a href="/view/campaigns">Campaigns</a>'
    '<a href="/view/orders">Orders</a>'
    '<a href="/view/map">Map</a>'
    '<a href="/view/settings">Settings</a>'
    "</ui-nav-menu>"
)

_OPEN_FROM_ADMIN = (
    "<!doctype html><meta charset=utf-8><title>Halia</title>"
    "<body style='font:16px system-ui;padding:48px;color:#1c1b18'>"
    "<h2>Halia</h2><p>Open this app from your Shopify admin (Apps → Halia) "
    "so it can load securely.</p></body>"
)

# Public marketing site — served at the root to any visitor who isn't an authenticated
# Shopify admin (i.e. the general public). Falls back to the stub if the file is missing.
from config import ROOT as _ROOT  # noqa: E402

_SITE_FILE = _ROOT / "web" / "site" / "index.html"


def _marketing(host: str = "") -> str:
    """The public front door, resolved by Host so one deployment serves both brands:
    haliascore.com -> the Halia site, storeconcierge.app -> the Store Concierge site.
    Only the Halia site carries the CMS overrides + shared site scripts (analytics, chat);
    the Store Concierge page is self-contained."""
    from halia.brands import brand_for_host
    b = brand_for_host(host)
    site_file = _ROOT / "web" / "site" / f"{b.landing}.html"
    try:
        html = site_file.read_text(encoding="utf-8")
    except OSError:
        return _OPEN_FROM_ADMIN
    if b.key == "halia":
        from halia.api.content import apply_overrides, with_site_scripts
        html = with_site_scripts(apply_overrides(html))
    return html


def _csp(shop: str) -> str:
    return f"frame-ancestors https://{shop} https://admin.shopify.com;"


def _head(shop: str = "") -> str:
    """App Bridge boot HTML. The apiKey must match the app the admin is loading — a custom-
    distribution bridge tenant's own app, else the public Halia app."""
    from halia.api.shopify_auth import credentials_for_shop
    key = credentials_for_shop(shop)[0] if shop else config.SHOPIFY_API_KEY
    return _HEAD.format(key=key or "")


def _pending_payload() -> dict:
    """An empty dashboard payload flagged sync_running, so the SPA shows the scoring screen."""
    return {"segments": {}, "data": [], "orders": [], "landscape": {}, "platform": "shopify",
            "stat_scored": "", "stat_latent": "", "stat_count": "", "stat_avgspend": "",
            "stat_toptier": "", "full_history": True, "locked_count": 0, "locked_latent": "",
            "sync_running": True}


def _error_page(head: str) -> str:
    # Generic — never echoes exception text (which could contain customer data).
    return (
        "<!doctype html><html><head>" + head + "</head>"
        "<body style='font:15px system-ui;padding:40px;color:#1c1b18'>"
        "<h2>Couldn't load your scores</h2>"
        "<p style='color:#6b675e;max-width:540px'>Halia hit a snag fetching from Shopify — "
        "usually transient. Hit <b>Refresh scores</b> (top right) to try again.</p></body></html>"
    )


def register(app) -> None:
    """Mount the embedded entry + per-shop API routes onto the FastAPI app."""

    def _serve_dashboard(request: Request):
        """Authenticate the embedded request and render the dashboard. Shared by "/" and the
        /app/<section> deep-link routes (the admin sidebar nav) — all serve the same SPA; the
        client reads the path to open the right section."""
        from build_mvp import render_payload

        try:
            session_token = token_for_request(request)
            shop = verify_session_token(session_token)
        except Exception:
            # public visitor → the marketing site for whichever brand this host serves
            return HTMLResponse(_marketing(request.headers.get("host", "")))

        head = _head(shop)
        try:
            entry = cache.get(shop)
            if entry is None:
                # First load (or a cold process): never run the full fetch + score inside the
                # install navigation. A large book takes longer than the edge proxy will wait and
                # the merchant sees a 502 instead of the app. Exchange the token now (fast), score
                # in the background, and render the "scoring your customers" screen, which polls
                # /v1/sync/state and reloads itself the moment the book is ready.
                from halia.api.onboarding import _start_sync
                from halia.api.shopify_auth import ensure_offline_token
                # Always exchange afresh here: a cold load is exactly when a stored token may be
                # dead (the app was uninstalled and reinstalled, as the review store did), and the
                # background sync has no session token of its own to self-heal with. One fast call.
                ensure_offline_token(shop, session_token, force=True)
                _start_sync(shop)
                body = render_payload(_pending_payload(), head_extra=head, body_extra=_NAV_MENU)
            else:
                body = render_payload(entry["payload"], head_extra=head, body_extra=_NAV_MENU)
        except Exception as exc:
            # Log the exception TYPE only (safe — never customer data) so the operator can tell
            # which stage failed: ShopifyAuthError=token/scopes, ShopifyError=fetch, HTTPException
            # =token exchange, anything else=score/render. Full stack follows (no payloads).
            print(f"[halia] dashboard load failed for {shop}: "
                  f"{type(exc).__module__}.{type(exc).__name__}")
            traceback.print_exc()  # stack only — no customer payloads are logged
            body = _error_page(head)

        resp = HTMLResponse(body)
        resp.headers["Content-Security-Policy"] = _csp(shop)
        resp.headers["Cache-Control"] = "no-store"  # always serve the latest dashboard
        return resp

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        return _serve_dashboard(request)

    # Admin sidebar deep-links (clients/catalogues/pipeline/orders/map/settings). Same dashboard;
    # the SPA reads the path and opens that section. Distinct paths are what let App Bridge
    # highlight the active nav item. (Under /view/ so it never collides with the self-serve /app/*
    # routes.)
    @app.get("/view/{section}", response_class=HTMLResponse)
    def app_section(section: str, request: Request):
        return _serve_dashboard(request)

    @app.get("/v1/sync/state")
    def sync_state(shop: str = Depends(require_shop)) -> dict:
        """Where the background scoring got to: running / done / error, plus whether the book
        is in memory now (the SPA polls this on first load and reloads on ready)."""
        from halia.api.onboarding import sync_status
        st = sync_status(shop)
        return {"state": st.get("state"), "error": st.get("error", ""),
                "ready": cache.get(shop) is not None}

    @app.post("/v1/sync")
    def sync_now(request: Request, shop: str = Depends(require_shop)):
        entry = data.sync_shop_authed(shop, token_for_request(request))
        return {"shop": shop, "hidden_vics": len(data.hidden_results(entry))}

    @app.get("/v1/dashboard")
    def dashboard_data(shop: str = Depends(require_shop)):
        entry = data.results_for(shop)
        if entry is None:
            return JSONResponse([])
        return JSONResponse([r.to_dict() for r in data.hidden_results(entry, 200)])
