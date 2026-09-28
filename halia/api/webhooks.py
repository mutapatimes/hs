"""Shopify mandatory compliance webhooks (GDPR) + app uninstall — HMAC authenticated.

Shopify requires every app that can access customer data to handle three privacy topics and
to reject any request whose HMAC doesn't verify (HTTP 401). Because Halia is zero-retention,
these are simple to satisfy honestly:

  customers/data_request → we hold NO customer data → acknowledge (nothing to return).
  customers/redact       → nothing stored → evict any in-RAM cache for the shop.
  shop/redact            → erase the shop's secrets (token + Klaviyo key) + evict cache.
  app/uninstalled        → same cleanup as shop/redact.

Webhooks carry no session token; they authenticate by an HMAC of the raw body signed with
the app's API secret. One endpoint handles all topics (dispatch on X-Shopify-Topic).

Docs: https://shopify.dev/docs/apps/build/compliance/privacy-law-compliance
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from fastapi import HTTPException, Request

from halia import config
from halia.cache import cache
from halia.store import ShopStore


def verify_hmac(raw_body: bytes, header: str, secret: str | None) -> bool:
    """True if the base64 HMAC-SHA256 of the raw body (keyed by the app secret) matches."""
    if not secret or not header:
        return False
    digest = base64.b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(digest, header)


_TOPICS = ("customers/data_request", "customers/redact", "shop/redact", "app/uninstalled")


def register(app) -> None:

    @app.post("/webhooks/shopify")
    async def shopify_webhook(request: Request):
        raw = await request.body()
        # A webhook may come from the public app OR any custom-distribution bridge app, each
        # signing with its own secret — accept a valid signature from any of ours.
        header = request.headers.get("X-Shopify-Hmac-Sha256", "")
        secrets = [config.SHOPIFY_API_SECRET] + [s for _, s in config.SHOPIFY_CUSTOM_APPS.values()]
        if not any(verify_hmac(raw, header, s) for s in secrets):
            raise HTTPException(401, "Invalid webhook HMAC")  # Shopify requirement

        topic = request.headers.get("X-Shopify-Topic", "")
        if topic not in _TOPICS:
            raise HTTPException(400, "Unknown topic")
        header_shop = request.headers.get("X-Shopify-Shop-Domain", "").strip().lower()
        # SECURITY: the HMAC signs the BODY, not the headers. The body must therefore be a real
        # Shopify payload (JSON) and the shop it acts on must come from that signed body:
        # shop_domain on the privacy topics, myshopify_domain on app/uninstalled. A signature over
        # arbitrary bytes, however obtained, cannot name a target through the unsigned header.
        try:
            body = json.loads(raw.decode() or "")
            if not isinstance(body, dict):
                raise ValueError("not an object")
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "Body must be a JSON object")
        body_shop = str(body.get("shop_domain") or body.get("myshopify_domain") or "").strip().lower()
        if not body_shop:
            raise HTTPException(400, "Payload names no shop")
        if header_shop and body_shop != header_shop:
            raise HTTPException(400, "Shop mismatch")
        shop = body_shop

        if topic in ("shop/redact", "app/uninstalled"):
            ShopStore().delete_shop(shop)   # erase the only thing we persist for this shop
            cache.evict(shop)
        elif topic == "customers/redact":
            cache.evict(shop)               # nothing persisted; clear any transient RAM
        # customers/data_request: we hold no customer data — nothing to return.

        return {"ok": True, "topic": topic}
