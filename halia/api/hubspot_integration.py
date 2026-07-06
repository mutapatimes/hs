"""Per-shop HubSpot integration — in-app actions, reading from the RAM cache only.

Each merchant connects THEIR HubSpot Private App token (stored encrypted). The contacts pushed
come from the in-memory cache, never a database.

    GET  /v1/hubspot/status                     — connected?
    POST /v1/hubspot/connect {api_token}        — store token, create the Halia contact properties
    POST /v1/hubspot/push {customer_ids?}       — upsert all hidden VICs, or a chosen few
    POST /v1/hubspot/list {customer_ids, name}  — make a static list from a selection
    POST /v1/hubspot/disconnect
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, HTTPException

from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store


def _entry_or_404(shop: str) -> dict:
    entry = data.results_for(shop)
    if entry is None:
        raise HTTPException(404, "No scored data for this shop yet — open the dashboard first.")
    return entry


def _conn_or_400(shop: str) -> dict:
    conn = shop_store().get_hubspot(shop)
    if not conn or not conn.get("api_token"):
        raise HTTPException(400, "Connect HubSpot first (add your Private App token).")
    return conn


def register(app) -> None:

    @app.get("/v1/hubspot/status")
    def hubspot_status(shop: str = Depends(require_shop)) -> dict:
        conn = shop_store().get_hubspot(shop)
        return {"connected": bool(conn and conn.get("api_token")),
                "portal_id": (conn or {}).get("portal_id") or ""}

    @app.post("/v1/hubspot/connect")
    def hubspot_connect(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        from halia.adapters.hubspot_sink import HubSpotError, HubSpotSink, validate_token

        token = str((payload or {}).get("api_token", "")).strip()
        if not token:
            raise HTTPException(422, "Paste your HubSpot Private App token.")
        try:
            validate_token(token)               # a cheap authed GET; raises if the token is bad
            HubSpotSink(token).ensure_properties()
        except HubSpotError as exc:
            raise HTTPException(422, f"HubSpot rejected that token: {exc}")
        shop_store().save_hubspot(shop, token, "")
        return {"connected": True}

    @app.post("/v1/hubspot/disconnect")
    def hubspot_disconnect(shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_hubspot(shop)
        return {"connected": False}

    @app.post("/v1/hubspot/push")
    def hubspot_push(shop: str = Depends(require_shop), payload: Any = Body(None)) -> dict:
        conn = _conn_or_400(shop)
        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") if isinstance(payload, dict) else None
        results = ([data.result_by_id(entry, c) for c in ids] if ids
                   else data.hidden_results(entry))
        targets = [r for r in results if r and r.flagged and r.email]
        if not targets:
            return {"pushed": 0}
        from halia.adapters.hubspot_sink import HubSpotError, HubSpotSink

        try:
            pushed = HubSpotSink(conn["api_token"]).push_many(targets)
        except HubSpotError as exc:
            raise HTTPException(502, f"HubSpot rejected the push: {exc}")
        data.record_activity(shop, "action_hubspot_push", pushed)
        return {"pushed": pushed}

    @app.post("/v1/hubspot/list")
    def hubspot_list(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        conn = _conn_or_400(shop)
        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") or []
        name = str((payload or {}).get("name") or "").strip() or "Halia selection"
        targets = [r for r in (data.result_by_id(entry, c) for c in ids) if r and r.email]
        if not targets:
            raise HTTPException(400, "No emailable clients selected.")
        from halia.adapters.hubspot_sink import HubSpotError, HubSpotSink, create_static_list

        try:
            written = HubSpotSink(conn["api_token"]).upsert(targets)  # ensure they exist + get ids
            contact_ids = [w["id"] for w in written if w.get("id")]
            lst = create_static_list(conn["api_token"], name, contact_ids)
        except HubSpotError as exc:
            raise HTTPException(502, f"HubSpot rejected it: {exc}")
        data.record_activity(shop, "action_hubspot_list")
        return {"list": lst, "count": len(targets)}
