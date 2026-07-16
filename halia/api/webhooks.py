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


def register(app) -> None:

    @app.post("/webhooks/shopify")
    async def shopify_webhook(request: Request):
        raw = await request.body()
        if not verify_hmac(raw, request.headers.get("X-Shopify-Hmac-Sha256", ""),
                           config.SHOPIFY_API_SECRET):
            raise HTTPException(401, "Invalid webhook HMAC")  # Shopify requirement

        topic = request.headers.get("X-Shopify-Topic", "")
        header_shop = request.headers.get("X-Shopify-Shop-Domain", "")
        # SECURITY: the HMAC signs the BODY, not the headers, so the destructive delete target is
        # taken from the signed JSON body (Shopify includes shop_domain), and only trusted when it
        # agrees with the unsigned header. Falls back to the header when the body omits it.
        try:
            body_shop = (json.loads(raw.decode() or "{}").get("shop_domain") or "").strip()
        except Exception:  # noqa: BLE001
            body_shop = ""
        shop = body_shop or header_shop
        if body_shop and header_shop and body_shop != header_shop:
            raise HTTPException(400, "Shop mismatch")

        if topic in ("shop/redact", "app/uninstalled"):
            ShopStore().delete_shop(shop)   # erase the only thing we persist for this shop
            cache.evict(shop)
        elif topic == "customers/redact":
            cache.evict(shop)               # nothing persisted; clear any transient RAM
        # customers/data_request: we hold no customer data — nothing to return.

        return {"ok": True, "topic": topic}
