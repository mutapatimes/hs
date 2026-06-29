"""Per-shop Mailchimp integration — in-app actions, reading from the RAM cache only.

Each merchant connects THEIR Mailchimp API key (stored encrypted) and picks an audience.
The customers pushed come from the in-memory cache, never a database.

    GET  /v1/mailchimp/status              — connected? which audience?
    POST /v1/mailchimp/connect {api_key, list_id?} — store key, pick audience, create merge fields
    POST /v1/mailchimp/push {customer_ids?}        — upsert all hidden VICs, or a chosen few
    POST /v1/mailchimp/segment {customer_ids,name} — make a static segment from a selection
    POST /v1/mailchimp/disconnect
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
    conn = shop_store().get_mailchimp(shop)
    if not conn or not conn.get("list_id"):
        raise HTTPException(400, "Connect Mailchimp first (add your API key and pick an audience).")
    return conn


def register(app) -> None:

    @app.get("/v1/mailchimp/status")
    def mailchimp_status(shop: str = Depends(require_shop)) -> dict:
        conn = shop_store().get_mailchimp(shop)
        return {"connected": bool(conn and conn.get("list_id")),
                "list_name": (conn or {}).get("list_name")}

    @app.post("/v1/mailchimp/connect")
    def mailchimp_connect(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        from halia.adapters.mailchimp_sink import (
            MailchimpError, MailchimpSink, dc_from_key, list_audiences,
        )

        key = str((payload or {}).get("api_key", "")).strip()
        try:
            dc_from_key(key)  # validates the …-dc shape
            audiences = list_audiences(key)
        except MailchimpError as exc:
            raise HTTPException(422, str(exc))
        if not audiences:
            raise HTTPException(422, "No Mailchimp audiences found on that account.")

        chosen = str((payload or {}).get("list_id") or "").strip()
        match = next((a for a in audiences if a["id"] == chosen), audiences[0])
        try:
            MailchimpSink(key, match["id"]).ensure_merge_fields()
        except MailchimpError as exc:
            raise HTTPException(502, f"Mailchimp rejected setup: {exc}")
        shop_store().save_mailchimp(shop, key, match["id"], match["name"])
        return {"connected": True, "list_id": match["id"], "list_name": match["name"],
                "audiences": audiences}

    @app.post("/v1/mailchimp/disconnect")
    def mailchimp_disconnect(shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_mailchimp(shop)
        return {"connected": False}

    @app.post("/v1/mailchimp/push")
    def mailchimp_push(shop: str = Depends(require_shop), payload: Any = Body(None)) -> dict:
        conn = _conn_or_400(shop)
        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") if isinstance(payload, dict) else None
        results = ([data.result_by_id(entry, c) for c in ids] if ids
                   else data.hidden_results(entry))
        targets = [r for r in results if r and r.flagged and r.email]
        if not targets:
            return {"pushed": 0}
        from halia.adapters.mailchimp_sink import MailchimpError, MailchimpSink

        try:
            pushed = MailchimpSink(conn["api_key"], conn["list_id"]).push_many(targets)
        except MailchimpError as exc:
            raise HTTPException(502, f"Mailchimp rejected the push: {exc}")
        return {"pushed": pushed, "list_name": conn["list_name"]}

    @app.post("/v1/mailchimp/segment")
    def mailchimp_segment(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        conn = _conn_or_400(shop)
        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") or []
        name = str((payload or {}).get("name") or "").strip() or "Halia selection"
        targets = [r for r in (data.result_by_id(entry, c) for c in ids) if r and r.email]
        if not targets:
            raise HTTPException(400, "No emailable clients selected.")
        from halia.adapters.mailchimp_sink import (
            MailchimpError, MailchimpSink, create_static_segment,
        )

        sink = MailchimpSink(conn["api_key"], conn["list_id"])
        try:
            sink.push_many(targets)  # ensure they exist on the audience first
            seg = create_static_segment(conn["api_key"], conn["list_id"], name,
                                        [r.email for r in targets])
        except MailchimpError as exc:
            raise HTTPException(502, f"Mailchimp rejected it: {exc}")
        return {"segment": seg, "count": len(targets), "list_name": conn["list_name"]}
