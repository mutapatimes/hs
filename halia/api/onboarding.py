"""Self-service onboarding + hosted dashboard for non-Shopify clients (WooCommerce now).

A client connects their store at **/connect**: store URL + read-only WooCommerce REST keys
(plus the signup code, if one is configured). We validate the creds with one live read,
create a tenant with the creds encrypted, and hand back a private dashboard link
(**/app?t=<token>**). The dashboard pulls + scores in RAM (zero-retention) and shows their
hidden VICs + Settings. No env files, no engineer in the loop.

First load triggers a background sync (a full store pull can take a while) and shows a
"preparing" page that auto-refreshes; once the RAM cache is warm the dashboard renders.
"""
from __future__ import annotations

import html
import re
import threading
import traceback

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from halia import config
from halia.api import data
from halia.api.shopify_auth import shop_store
from halia.api.tenant_auth import COOKIE, hash_token, new_token, require_tenant, resolve_tenant
from halia.cache import cache

# Shops currently being scored in a background thread (so we don't double-trigger).
_SYNCING: set[str] = set()
_LOCK = threading.Lock()

_CSS = (
    "body{margin:0;background:#f1f1f1;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',"
    "Roboto,Helvetica,Arial,sans-serif;color:#303030}.wrap{max-width:560px;margin:0 auto;"
    "padding:48px 20px 80px}.card{background:#fff;border:1px solid #e3e3e3;border-radius:12px;"
    "padding:24px}h1{font:650 24px system-ui;margin:0 0 6px}.sub{color:#616161;font-size:14px;"
    "margin:0 0 22px}label{display:block;font:600 13px system-ui;margin:14px 0 5px}"
    "input{width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid #8a8a8a;"
    "border-radius:8px;font:14px system-ui}.help{font-size:12px;color:#616161;margin:4px 0 0}"
    ".btn{margin-top:22px;background:#303030;color:#fff;border:none;border-radius:8px;"
    "padding:12px 20px;font:600 14px system-ui;cursor:pointer}.err{background:#fff1f0;"
    "border:1px solid #e0b4b0;color:#8e1f0b;border-radius:8px;padding:10px 12px;font-size:13px;"
    "margin-bottom:16px}.ok{color:#0f7b4f}a.link{color:#1f564a;font-weight:600}"
    "code{background:#f1f1f1;padding:2px 6px;border-radius:5px;font-size:13px;word-break:break-all}"
)


def _page(title: str, inner: str) -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><title>{title}</title>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<style>{_CSS}</style></head><body><div class=wrap>{inner}</div></body></html>")


def _slug(url: str) -> str:
    bare = re.sub(r"^https?://", "", (url or "").lower()).strip("/")
    return re.sub(r"[^a-z0-9]+", "-", bare).strip("-")


def _validate_woo(store_url: str, ck: str, cs: str, probe=None) -> tuple[bool, str]:
    """One live read-only call to confirm the credentials work. `probe` is injectable."""
    try:
        if probe is None:
            from scoring.woocommerce_fetch import http_transport
            probe = http_transport(store_url, ck, cs)
        probe("orders", {"per_page": 1})
        return True, ""
    except Exception as exc:  # noqa: BLE001 — surface a short reason to the client
        return False, str(exc)[:180]


def _start_sync(shop: str) -> None:
    """Kick a background scoring sync for a tenant (idempotent)."""
    with _LOCK:
        if shop in _SYNCING:
            return
        _SYNCING.add(shop)

    def _run():
        try:
            data.sync_tenant(shop)
        except Exception:
            traceback.print_exc()  # stack only — never customer data
        finally:
            with _LOCK:
                _SYNCING.discard(shop)

    threading.Thread(target=_run, daemon=True).start()


def _connect_form(error: str = "", values: dict | None = None) -> str:
    v = values or {}
    code_field = ""
    if config.SIGNUP_CODE:
        code_field = ("<label>Signup code</label>"
                      "<input name=code type=password placeholder='from your Halia contact'>"
                      "<div class=help>Required to create an account.</div>")
    err = f"<div class=err>{html.escape(error)}</div>" if error else ""
    return _page("Connect your store — Halia", f"""
      <h1>Connect your store</h1>
      <p class=sub>Halia scores your customers for hidden VICs. Connect a read-only
      WooCommerce key — we never write to your store, and never store your customers.</p>
      <div class=card>{err}
      <form method=post action=/connect>
        <label>Store name</label>
        <input name=label placeholder='e.g. Glen Norah' value="{html.escape(v.get('label',''))}">
        <label>Store URL</label>
        <input name=store_url placeholder='https://yourstore.com' value="{html.escape(v.get('store_url',''))}">
        <label>WooCommerce consumer key</label>
        <input name=consumer_key placeholder='ck_…' value="{html.escape(v.get('consumer_key',''))}">
        <div class=help>WooCommerce → Settings → Advanced → REST API → Add key → permission <b>Read</b>.</div>
        <label>WooCommerce consumer secret</label>
        <input name=consumer_secret type=password placeholder='cs_…'>
        {code_field}
        <button class=btn type=submit>Connect &amp; score</button>
      </form></div>""")


def _hosted_head() -> str:
    # A refresh button for the hosted dashboard (re-pull + re-score), no App Bridge.
    return (
        "<style>#halia-refresh{position:fixed;top:14px;right:18px;z-index:200;padding:8px 14px;"
        "border-radius:8px;border:1px solid #d8c79a;background:#1f564a;color:#fff;"
        "font:600 13px system-ui;cursor:pointer}#halia-refresh[disabled]{opacity:.6}</style>"
        "<script>addEventListener('DOMContentLoaded',function(){var b=document.createElement('button');"
        "b.id='halia-refresh';b.textContent='\\u21bb Refresh scores';b.onclick=function(){"
        "b.disabled=true;b.textContent='Refreshing\\u2026';fetch('/app/refresh',{method:'POST'})"
        ".then(function(r){return r.json()}).then(function(){location.reload()})"
        ".catch(function(){b.textContent='Refresh failed';b.disabled=false})};"
        "document.body.appendChild(b)});</script>"
    )


def _preparing_page() -> HTMLResponse:
    inner = ("<h1>Scoring your store…</h1>"
             "<p class=sub>We're pulling your orders and scoring your customers. This can take "
             "a minute or two the first time — this page refreshes itself.</p>"
             "<div class=card><div style='display:flex;gap:10px;align-items:center'>"
             "<div class='spin' style='width:18px;height:18px;border:3px solid #d8d8d8;"
             "border-top-color:#1f564a;border-radius:50%;animation:s 1s linear infinite'></div>"
             "<span style='color:#616161;font-size:14px'>Working…</span></div></div>"
             "<style>@keyframes s{to{transform:rotate(360deg)}}</style>")
    resp = HTMLResponse(_page("Scoring… — Halia", inner))
    resp.headers["Refresh"] = "5"  # browser re-requests /app every 5s
    resp.headers["Cache-Control"] = "no-store"
    return resp


def register(app) -> None:
    """Mount the self-service onboarding + hosted dashboard routes."""

    @app.get("/connect", response_class=HTMLResponse)
    def connect_form():
        return HTMLResponse(_connect_form())

    @app.post("/connect", response_class=HTMLResponse)
    def connect_submit(
        store_url: str = Form(...),
        consumer_key: str = Form(...),
        consumer_secret: str = Form(...),
        label: str = Form(""),
        code: str = Form(""),
    ):
        values = {"store_url": store_url, "consumer_key": consumer_key, "label": label}
        if config.SIGNUP_CODE and code.strip() != config.SIGNUP_CODE:
            return HTMLResponse(_connect_form("Wrong signup code.", values), status_code=403)

        store_url = store_url.strip().rstrip("/")
        shop = _slug(store_url)
        if not shop or not store_url.startswith("http"):
            return HTMLResponse(_connect_form("Enter a full store URL (https://…).", values), 400)

        ok, why = _validate_woo(store_url, consumer_key.strip(), consumer_secret.strip())
        if not ok:
            return HTMLResponse(_connect_form(
                f"Couldn't reach WooCommerce with those keys: {why}", values), 400)

        token = new_token()
        store = shop_store()
        store.create_tenant(shop, "woocommerce", label.strip() or shop, hash_token(token))
        store.save_woocommerce(shop, store_url, consumer_key.strip(), consumer_secret.strip())
        _start_sync(shop)  # warm the cache while they read the success page

        link = f"/app?t={token}"
        inner = (f"<h1 class=ok>✓ {html.escape(label.strip() or shop)} connected</h1>"
                 "<p class=sub>Your private dashboard is ready. Bookmark this link — it's the "
                 "only way in, so keep it safe.</p>"
                 f"<div class=card><p style='margin:0 0 14px'><a class=link href='{link}'>"
                 "Open my dashboard →</a></p>"
                 f"<div class=help>Private link</div><code>{html.escape(link)}</code></div>")
        return HTMLResponse(_page("Connected — Halia", inner))

    @app.get("/app", response_class=HTMLResponse)
    def hosted_dashboard(request: Request):
        from build_mvp import render_payload

        # First arrival carries ?t=<token>: set the cookie and redirect to a clean URL.
        if request.query_params.get("t"):
            shop = resolve_tenant(request)
            if not shop:
                return HTMLResponse(_page("Halia", "<h1>Invalid link</h1><p class=sub>This access "
                                          "link isn't valid. Ask your Halia contact for a new one.</p>"), 401)
            resp = RedirectResponse("/app", status_code=303)
            resp.set_cookie(COOKIE, request.query_params["t"], httponly=True,
                            secure=request.url.scheme == "https", samesite="lax",
                            max_age=60 * 60 * 24 * 365)
            return resp

        shop = require_tenant(request)
        entry = cache.get(shop)
        if entry is None:
            _start_sync(shop)
            return _preparing_page()
        try:
            body = render_payload(entry["payload"], head_extra=_hosted_head())
        except Exception:
            traceback.print_exc()
            return HTMLResponse(_page("Halia", "<h1>Couldn't load your scores</h1>"
                                      "<p class=sub>Hit refresh in a moment.</p>"), 500)
        resp = HTMLResponse(body)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/app/refresh")
    def hosted_refresh(request: Request):
        shop = require_tenant(request)
        cache.evict(shop)
        entry = data.sync_tenant(shop)
        return {"shop": shop, "hidden_vics": len(data.hidden_results(entry)) if entry else 0}
