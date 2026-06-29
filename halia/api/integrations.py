"""Per-shop Klaviyo integration — the in-app actions that actually do something.

The dashboard's old "Push to Klaviyo" / "Push to email" buttons were mockups (toasts).
These routes make them real and multi-tenant: each merchant connects THEIR Klaviyo
private key (stored per shop), and the app upserts the hidden-VICs as Klaviyo profiles
with Halia grade properties (and ensures the default grade segments exist on connect).

    GET  /v1/klaviyo/status            — is this shop connected?
    POST /v1/klaviyo/connect {api_key} — store the key + create default segments
    POST /v1/klaviyo/push {customer_ids?} — push all hidden VICs, or a chosen few
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Depends, HTTPException

from halia import config
from halia.api.shopify_auth import require_shop
from halia.store import ShopStore


def _key_for(shop: str) -> Optional[str]:
    """This shop's Klaviyo key, falling back to a server-wide key if one is set."""
    return ShopStore().get_klaviyo(shop) or config.KLAVIYO_API_KEY


def register(app, get_store) -> None:

    @app.get("/v1/klaviyo/status")
    def klaviyo_status(shop: str = Depends(require_shop)) -> dict:
        return {"connected": bool(_key_for(shop))}

    @app.post("/v1/klaviyo/connect")
    def klaviyo_connect(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        key = str((payload or {}).get("api_key", "")).strip()
        if not key.startswith("pk_"):
            raise HTTPException(422, "Enter your Klaviyo PRIVATE API key (starts with pk_).")
        ShopStore().save_klaviyo(shop, key)
        from halia.adapters.klaviyo_segments import KlaviyoSegments

        try:
            segments = KlaviyoSegments(api_key=key).ensure_defaults()
        except Exception as exc:  # key works for profiles but lacks segment scope, etc.
            segments = {"warning": str(exc)[:200]}
        return {"connected": True, "segments": segments}

    @app.post("/v1/klaviyo/event")
    def klaviyo_event(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        """One-click 'email this client': ensure their profile + grade, then fire the
        'Halia VIC Identified' event so the merchant's Klaviyo flow sends the email."""
        key = _key_for(shop)
        if not key:
            raise HTTPException(400, "Connect Klaviyo first (add your private API key).")
        result = get_store().get_by_customer_id(shop, (payload or {}).get("customer_id"))
        if not result or not result.email:
            raise HTTPException(404, "No emailable customer for that id.")
        from halia.adapters.klaviyo_events import METRIC, fire_event
        from halia.adapters.klaviyo_sink import KlaviyoError, KlaviyoSink

        try:
            KlaviyoSink(api_key=key).push_one(result)  # profile + Halia grade properties
            fire_event(key, result)                    # trigger the flow
        except KlaviyoError as exc:
            raise HTTPException(502, f"Klaviyo rejected it: {exc}")
        return {"ok": True, "metric": METRIC, "email": result.email}

    @app.post("/v1/klaviyo/open")
    def klaviyo_open(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        """Ensure the client is in Klaviyo and return a deep link to their profile —
        so the merchant lands right where they can email / flow / action them."""
        key = _key_for(shop)
        if not key:
            raise HTTPException(400, "Connect Klaviyo first (add your private API key).")
        cid = (payload or {}).get("customer_id")
        result = get_store().get_by_customer_id(shop, cid)
        if not result or not result.email:
            raise HTTPException(404, "No emailable customer for that id.")
        from halia.adapters.klaviyo_sink import KlaviyoError, KlaviyoSink

        try:
            resp = KlaviyoSink(api_key=key).push_one(result)  # upserts + returns the profile
        except KlaviyoError as exc:
            raise HTTPException(502, f"Klaviyo rejected it: {exc}")
        pid = (resp.get("data") or {}).get("id")
        if not pid:
            raise HTTPException(502, "Klaviyo didn't return a profile id.")
        return {"url": f"https://www.klaviyo.com/profile/{pid}"}

    @app.post("/v1/klaviyo/push")
    def klaviyo_push(shop: str = Depends(require_shop), payload: Any = Body(None)) -> dict:
        key = _key_for(shop)
        if not key:
            raise HTTPException(400, "Connect Klaviyo first (add your private API key).")
        store = get_store()
        ids = (payload or {}).get("customer_ids") if isinstance(payload, dict) else None
        if ids:
            results = [store.get_by_customer_id(shop, c) for c in ids]
        else:
            results = store.top_hidden(shop, 1000)
        targets = [r for r in results if r and r.flagged and r.email]
        if not targets:
            return {"pushed": 0}
        from halia.adapters.klaviyo_sink import KlaviyoError, KlaviyoSink

        try:
            KlaviyoSink(api_key=key).push_many(targets)
        except KlaviyoError as exc:
            raise HTTPException(502, f"Klaviyo rejected the push: {exc}")
        return {"pushed": len(targets)}
