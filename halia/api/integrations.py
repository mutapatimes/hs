"""Per-shop Klaviyo integration — the in-app actions, reading from the RAM cache only.

Each merchant connects THEIR Klaviyo private key (stored encrypted, the one persisted
secret). The customers being pushed/emailed come from the in-memory cache, never a database.

    GET  /v1/klaviyo/status            — is this shop connected?
    POST /v1/klaviyo/connect {api_key} — store the key + create default segments
    POST /v1/klaviyo/push {customer_ids?} — upsert all hidden VICs, or a chosen few
    POST /v1/klaviyo/event {customer_id}  — fire the "Halia VIC Identified" flow trigger
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Depends, HTTPException

from halia import config
from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store


def _key_for(shop: str) -> Optional[str]:
    """This shop's Klaviyo key, falling back to a server-wide key if one is set."""
    return shop_store().get_klaviyo(shop) or config.KLAVIYO_API_KEY


def _entry_or_404(shop: str) -> dict:
    entry = data.results_for(shop)
    if entry is None:
        raise HTTPException(404, "No scored data for this shop yet — open the dashboard first.")
    return entry


def register(app) -> None:

    @app.get("/v1/klaviyo/status")
    def klaviyo_status(shop: str = Depends(require_shop)) -> dict:
        return {"connected": bool(_key_for(shop))}

    @app.post("/v1/klaviyo/connect")
    def klaviyo_connect(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        key = str((payload or {}).get("api_key", "")).strip()
        if not key.startswith("pk_"):
            raise HTTPException(422, "Enter your Klaviyo PRIVATE API key (starts with pk_).")
        shop_store().save_klaviyo(shop, key)
        from halia.adapters.klaviyo_segments import KlaviyoSegments

        try:
            segments = KlaviyoSegments(api_key=key).ensure_defaults()
        except Exception as exc:
            segments = {"warning": str(exc)[:200]}
        return {"connected": True, "segments": segments}

    @app.post("/v1/klaviyo/event")
    def klaviyo_event(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        """One-click 'email this client': ensure profile + grade, then fire the flow event."""
        key = _key_for(shop)
        if not key:
            raise HTTPException(400, "Connect Klaviyo first (add your private API key).")
        result = data.result_by_id(_entry_or_404(shop), (payload or {}).get("customer_id"))
        if not result or not result.email:
            raise HTTPException(404, "No emailable customer for that id.")
        from halia.adapters.klaviyo_events import METRIC, fire_event
        from halia.adapters.klaviyo_sink import KlaviyoError, KlaviyoSink

        try:
            KlaviyoSink(api_key=key).push_one(result)
            fire_event(key, result)
        except KlaviyoError as exc:
            raise HTTPException(502, f"Klaviyo rejected it: {exc}")
        return {"ok": True, "metric": METRIC, "email": result.email}

    @app.post("/v1/klaviyo/open")
    def klaviyo_open(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        """Upsert the client and return a deep link to their Klaviyo profile."""
        key = _key_for(shop)
        if not key:
            raise HTTPException(400, "Connect Klaviyo first (add your private API key).")
        result = data.result_by_id(_entry_or_404(shop), (payload or {}).get("customer_id"))
        if not result or not result.email:
            raise HTTPException(404, "No emailable customer for that id.")
        from halia.adapters.klaviyo_sink import KlaviyoError, KlaviyoSink

        try:
            resp = KlaviyoSink(api_key=key).push_one(result)
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
        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") if isinstance(payload, dict) else None
        if ids:
            results = [data.result_by_id(entry, c) for c in ids]
        else:
            results = data.hidden_results(entry)
        targets = [r for r in results if r and r.flagged and r.email]
        if not targets:
            return {"pushed": 0}
        from halia.adapters.klaviyo_sink import KlaviyoError, KlaviyoSink

        try:
            KlaviyoSink(api_key=key).push_many(targets)
        except KlaviyoError as exc:
            raise HTTPException(502, f"Klaviyo rejected the push: {exc}")
        return {"pushed": len(targets)}
