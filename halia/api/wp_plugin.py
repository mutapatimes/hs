"""The WordPress plugin's doorway: one call connects a WooCommerce store.

The plugin mints a read/write REST key inside the merchant's own site and posts it here with
the store address. Halia validates it with one read, creates (or refreshes) the tenant, starts
the first scoring run, registers the per-shop order-webhook URL the plugin will subscribe to,
and hands back the merchant's private sign-in link. Same tenant model as every other Woo store;
only the onboarding form is replaced by a button in wp-admin.

    POST /connect/woocommerce/plugin
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import Body, HTTPException

from halia import config
from halia.api.shopify_auth import shop_store
from halia.api.tenant_auth import hash_token, new_token


def register(app) -> None:
    @app.post("/connect/woocommerce/plugin", include_in_schema=False)
    def connect_plugin(payload: Any = Body(...)) -> dict:
        from halia.api import onboarding as ob

        p = payload if isinstance(payload, dict) else {}
        store_url = str(p.get("store_url") or "").strip().rstrip("/")
        ck, cs = str(p.get("consumer_key") or "").strip(), str(p.get("consumer_secret") or "").strip()
        label = str(p.get("site_name") or "").strip()[:120]
        email = str(p.get("email") or "").strip().lower()
        if not store_url.startswith("http") or not ck or not cs:
            raise HTTPException(400, "The plugin needs the store address and a read/write REST key.")
        shop = ob._slug(store_url)
        if not shop:
            raise HTTPException(400, "That store address does not look right.")
        ok, why = ob._validate_woo(store_url, ck, cs)
        if not ok:
            raise HTTPException(400, f"Halia could not reach WooCommerce with that key: {why}")

        store = shop_store()
        existing = store.get_tenant(shop)
        link_token = None
        if existing is None:
            link_token = new_token()
            store.create_tenant(shop, "woocommerce", label or shop, hash_token(link_token))
        store.save_woocommerce(shop, store_url, ck, cs)
        webhook_token = store.ensure_webhook_token(shop, secrets.token_urlsafe(24))
        base = (config.HALIA_APP_URL or "").rstrip("/")
        try:
            ob._start_sync(shop, notify=bool(email))
        except Exception:  # noqa: BLE001 — the connection stands even if the warm-up hiccups
            pass
        open_url = f"{base}/app?t={link_token}" if link_token else f"{base}/app"
        if email and link_token:
            try:
                ob._send_welcome_signin_email(email, f"/app?t={link_token}", label or shop)
            except Exception:  # noqa: BLE001
                pass
        capture_url, capture_qr = "", None
        try:
            from halia.api.capture import _slug_for
            from halia.api.client_host import client_url, invalidate
            from halia.api.seats import _connect_qr
            invalidate(shop)
            capture_url = client_url(shop, f"c/{_slug_for(shop)}")
            capture_qr = _connect_qr(capture_url)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "shop": shop, "capture_url": capture_url, "capture_qr": capture_qr, "label": label or shop, "reconnected": existing is not None,
                "open_url": open_url, "dashboard": f"{base}/app",
                "webhook_url": f"{base}/webhooks/orders/{webhook_token}"}
