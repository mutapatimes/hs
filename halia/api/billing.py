"""Stripe billing: gate the hosted dashboard behind a subscription.

Free path: a merchant connects their store and sees a teaser (their hidden-VIC count and
the total latent value). To unlock the full dashboard they subscribe through Stripe Checkout.

Billing is OFF unless STRIPE_SECRET_KEY and STRIPE_PRICE_ID are both set, so existing and
local tenants stay fully open and no one is ever locked out by accident. Specific tenants can
be comped via HALIA_FREE_SHOPS.

    POST /v1/checkout      — create a Checkout Session, return its URL (auth: tenant cookie)
    POST /webhooks/stripe  — Stripe events: mark a tenant active / canceled

Stripe is called over its REST API with `requests` (no SDK dependency), mirroring the Brevo
email integration.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import Depends, HTTPException, Request

from halia import config
from halia.api.shopify_auth import require_shop, shop_store

_ACTIVE = {"active", "trialing", "comped", "complete"}


def billing_enabled() -> bool:
    return bool(config.STRIPE_SECRET_KEY and config.STRIPE_PRICE_ID)


def is_paid(shop: str) -> bool:
    """True if this tenant may see the full dashboard. Open when billing is off or comped."""
    if not billing_enabled():
        return True
    if shop in config.HALIA_FREE_SHOPS:
        return True
    b = shop_store().get_billing(shop)
    return bool(b and b.get("status") in _ACTIVE)


def _stripe(method: str, path: str, data: dict | None = None) -> dict:
    import requests

    resp = requests.request(method, f"https://api.stripe.com/v1/{path}",
                            auth=(config.STRIPE_SECRET_KEY, ""), data=data, timeout=20)
    if not (200 <= resp.status_code < 300):
        raise HTTPException(502, f"Stripe error: {resp.text[:200]}")
    return resp.json()


def create_checkout(shop: str) -> str:
    """Create a subscription Checkout Session for this tenant and return its hosted URL."""
    base = config.HALIA_APP_URL or ""
    data = {
        "mode": "subscription",
        "line_items[0][price]": config.STRIPE_PRICE_ID,
        "line_items[0][quantity]": "1",
        "client_reference_id": shop,
        "metadata[shop]": shop,
        "subscription_data[metadata][shop]": shop,
        "success_url": f"{base}/app?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/app",
        "allow_promotion_codes": "true",
    }
    return _stripe("POST", "checkout/sessions", data)["url"]


def confirm_session(shop: str, session_id: str) -> bool:
    """Verify a returning Checkout session and, if paid, mark the tenant active."""
    if not billing_enabled() or not session_id:
        return is_paid(shop)
    try:
        sess = _stripe("GET", f"checkout/sessions/{session_id}")
    except Exception:  # noqa: BLE001 — fall back to stored status
        return is_paid(shop)
    if sess.get("client_reference_id") and sess["client_reference_id"] != shop:
        return is_paid(shop)
    if sess.get("payment_status") == "paid" or sess.get("status") == "complete":
        shop_store().set_billing(shop, "active", sess.get("customer"), sess.get("subscription"))
        return True
    return is_paid(shop)


def _verify_sig(body: bytes, sig_header: str, secret: str) -> bool:
    """Verify a Stripe webhook signature (HMAC-SHA256 over `t.payload`)."""
    try:
        pairs = [p.split("=", 1) for p in sig_header.split(",")]
        t = next(v for k, v in pairs if k == "t")
        sigs = [v for k, v in pairs if k == "v1"]
        expected = hmac.new(secret.encode(), t.encode() + b"." + body, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, s) for s in sigs)
    except Exception:  # noqa: BLE001
        return False


def register(app) -> None:

    @app.post("/v1/checkout")
    def checkout(shop: str = Depends(require_shop)) -> dict:
        if not billing_enabled():
            return {"url": "/app"}  # nothing to pay for; the dashboard is already open
        return {"url": create_checkout(shop)}

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> dict:
        body = await request.body()
        if config.STRIPE_WEBHOOK_SECRET:
            if not _verify_sig(body, request.headers.get("stripe-signature", ""),
                               config.STRIPE_WEBHOOK_SECRET):
                raise HTTPException(400, "Bad signature")
        try:
            event = json.loads(body.decode() or "{}")
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Bad payload")
        obj = (event.get("data") or {}).get("object") or {}
        shop = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("shop")
        if not shop:
            return {"received": True}
        store = shop_store()
        typ = event.get("type", "")
        if typ == "checkout.session.completed":
            store.set_billing(shop, "active", obj.get("customer"), obj.get("subscription"))
        elif typ == "customer.subscription.deleted":
            store.set_billing(shop, "canceled")
        elif typ == "customer.subscription.updated":
            store.set_billing(shop, obj.get("status") or "active")
        return {"received": True}
