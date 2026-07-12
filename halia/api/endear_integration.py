"""Per-shop Endear integration — push hidden-VIC intelligence into the merchant's Endear CRM.

Each merchant connects THEIR Endear API key (stored encrypted). The customers pushed come from the
in-memory cache, never a database — Halia routes its scores into the merchant's own clienteling CRM.

    GET  /v1/endear/status
    POST /v1/endear/connect {api_key}       — store key, define the Halia customer fields
    POST /v1/endear/push {customer_ids?}    — upsert all hidden VICs (or a chosen few), tag + enrich
    POST /v1/endear/disconnect
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
    conn = shop_store().get_endear(shop)
    if not conn or not conn.get("api_key"):
        raise HTTPException(400, "Connect Endear first (add your Endear API key).")
    return conn


def register(app) -> None:

    @app.get("/v1/endear/status")
    def endear_status(shop: str = Depends(require_shop)) -> dict:
        conn = shop_store().get_endear(shop)
        return {"connected": bool(conn and conn.get("api_key"))}

    @app.post("/v1/endear/connect")
    def endear_connect(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        from halia.adapters.endear_sink import EndearError, EndearSink

        key = str((payload or {}).get("api_key", "")).strip()
        if not key:
            raise HTTPException(422, "Paste your Endear API key.")
        try:
            sink = EndearSink(key)
            sink.validate_key()                 # a cheap authed probe; raises if the key is bad
            sink.ensure_fields()                # define the Halia custom fields on the brand
        except EndearError as exc:
            raise HTTPException(422, f"Endear rejected that key: {exc}")
        shop_store().save_endear(shop, key)
        return {"connected": True}

    @app.post("/v1/endear/disconnect")
    def endear_disconnect(shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_endear(shop)
        return {"connected": False}

    @app.post("/v1/endear/push")
    def endear_push(shop: str = Depends(require_shop), payload: Any = Body(None)) -> dict:
        conn = _conn_or_400(shop)
        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") if isinstance(payload, dict) else None
        results = ([data.result_by_id(entry, c) for c in ids] if ids
                   else data.hidden_results(entry))
        targets = [r for r in results if r and r.flagged and (r.customer_id or r.email)]
        if not targets:
            return {"pushed": 0}
        from halia.adapters.endear_sink import EndearError, EndearSink

        try:
            pushed = EndearSink(conn["api_key"]).push_many(targets)
        except EndearError as exc:
            raise HTTPException(502, f"Endear rejected the push: {exc}")
        data.record_activity(shop, "action_endear_push", pushed)
        return {"pushed": pushed}
