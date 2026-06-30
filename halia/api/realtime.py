"""Real-time high-grade order alerts: order webhook -> score in memory -> push + email.

The store calls POST /webhooks/orders/{token} on each new order (a Shopify orders/create
webhook, or a WooCommerce "Order created" webhook). Halia resolves the shop from the token,
scores that one customer in memory, and if the grade meets the merchant's threshold it
dispatches a desktop Web Push and/or an email, and adds the order to the in-dashboard live
feed. Nothing about the customer is stored: it is scored and the alert sent, then forgotten.
"""
from __future__ import annotations

import html as _html
import traceback
from typing import Any

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from halia import notify
from halia.api import data
from halia.api.settings import settings_for
from halia.api.shopify_auth import require_shop, shop_store
from halia.cache import cache

# Service worker: shows the push and focuses the dashboard on click.
_SW = (
    "self.addEventListener('push',function(e){var d={};try{d=e.data.json()}catch(x){}"
    "e.waitUntil(self.registration.showNotification(d.title||'New high-grade order',"
    "{body:d.body||'',tag:d.tag||'halia',data:d,badge:'/img/badge.png'}));});"
    "self.addEventListener('notificationclick',function(e){e.notification.close();"
    "e.waitUntil(clients.matchAll({type:'window'}).then(function(ws){"
    "for(var i=0;i<ws.length;i++){if(ws[i].url.indexOf('/app')>-1&&'focus'in ws[i])return ws[i].focus();}"
    "return clients.openWindow((e.notification.data&&e.notification.data.url)||'/app');}));});"
)


def _email_html(a: dict, shop: str) -> str:
    name = _html.escape(str(a.get("name") or "A client"))
    signals = _html.escape(" · ".join(a.get("signals") or []))
    grade = _html.escape(str(a.get("grade") or ""))
    return (
        "<div style=\"font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;"
        "margin:0 auto;color:#1c1b18\">"
        f"<p style=\"font:600 12px sans-serif;letter-spacing:.12em;text-transform:uppercase;"
        f"color:#1f564a;margin:0 0 8px\">New {grade} order</p>"
        f"<h2 style=\"font:400 26px Georgia,serif;margin:0 0 6px\">{name}</h2>"
        f"<p style=\"color:#6b675e;margin:0 0 18px\">{signals or 'A high-grade client just ordered.'}</p>"
        "<a href=\"" + (a.get("url") or "/app") + "\" style=\"display:inline-block;background:#1f564a;"
        "color:#fff;text-decoration:none;font:600 14px sans-serif;padding:11px 20px;border-radius:8px\">"
        "Open in Halia</a>"
        "<p style=\"color:#9a958a;font-size:12px;margin:22px 0 0\">You are receiving this because order "
        "alerts are on in Halia. Turn them off any time in Settings.</p></div>"
    )


def _dispatch(shop: str, alert: dict, s: dict) -> None:
    store = shop_store()
    subs = store.push_subs(shop)
    if subs:
        notify.send_web_push(subs, {
            "title": f"New {alert['grade']} order · {alert['name']}",
            "body": " · ".join(alert.get("signals") or []) or "A high-grade client just ordered.",
            "tag": "halia-" + str(alert.get("order_id")), "url": "/app"})
    emails = s.get("notify_emails") or ([s["notify_email"]] if s.get("notify_email") else [])
    if emails and notify.email_configured():
        subject = f"New {alert['grade']} order · {alert['name']}"
        html = _email_html(alert, shop)
        for email in emails:
            notify.send_email(email, subject, html)


def register(app) -> None:

    @app.get("/sw.js")
    def service_worker() -> Response:
        return Response(_SW, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.post("/v1/push/subscribe")
    def push_subscribe(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        sub = payload or {}
        ep, keys = sub.get("endpoint"), (sub.get("keys") or {})
        if not ep or not keys.get("p256dh") or not keys.get("auth"):
            raise HTTPException(422, "Invalid push subscription.")
        shop_store().add_push_sub(shop, ep, keys["p256dh"], keys["auth"])
        return {"ok": True}

    @app.post("/v1/push/unsubscribe")
    def push_unsubscribe(payload: Any = Body(None)) -> dict:
        ep = (payload or {}).get("endpoint")
        if ep:
            shop_store().delete_push_sub(ep)
        return {"ok": True}

    @app.post("/webhooks/orders/{token}")
    async def order_webhook(token: str, request: Request) -> JSONResponse:
        shop = shop_store().shop_for_webhook(token)
        if not shop:
            return JSONResponse({"ok": False}, status_code=404)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001 — ping / non-JSON body, ack and move on
            return JSONResponse({"ok": True})
        try:
            s = settings_for(shop)
            alert = data.score_order(shop, payload)
            if alert and alert["grade"] in (s.get("notify_grades") or ["A*", "A"]):
                cache.add_alert(shop, alert)
                _dispatch(shop, alert, s)
        except Exception:  # noqa: BLE001 — never fail the store's webhook delivery
            traceback.print_exc()
        return JSONResponse({"ok": True})
