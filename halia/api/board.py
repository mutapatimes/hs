"""VIC outreach pipeline (kanban) — Shopify-backed, zero Halia persistence.

Board state lives entirely in the merchant's own Shopify store: a customer TAG ``Halia Stage: <s>``
(the column, natively segmentable) plus a ``halia.pipeline`` customer METAFIELD holding the assignee
and the activity log (with notes + attribution). Halia writes/reads these via the Admin API and keeps
nothing on its own disk, so the board is team-shared (everyone's Halia reads the same store) while
zero-retention is preserved. Shopify-only: attribution is the staff-user id from the session token.

    POST /v1/board/add     {cid}                       -> stage "To reach out"
    POST /v1/board/move    {cid, stage}
    POST /v1/board/assign  {cid, assignee_id, assignee_name}
    POST /v1/board/note    {cid, note}
    POST /v1/board/remove  {cid}
    GET  /v1/board                                      -> cards grouped by stage
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, Depends, HTTPException, Request

from halia.api.shopify_auth import current_staff_id, require_shop, shop_store
from scoring.shopify_pipeline import STAGES, stage_tag


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_pipe(raw: str | None) -> dict:
    """Parse a halia.pipeline metafield value into a normalised dict."""
    pipe = {}
    if raw:
        try:
            pipe = json.loads(raw)
        except (ValueError, TypeError):
            pipe = {}
    if not isinstance(pipe, dict):
        pipe = {}
    pipe.setdefault("stage", None)
    pipe.setdefault("assignee", None)
    pipe.setdefault("activity", [])
    return pipe


def append_activity(pipe: dict, action: str, actor_id: str | None, actor_name: str | None,
                    note: str | None = None) -> dict:
    """Append one attributed activity entry (capped) and stamp updated_at. Mutates + returns pipe."""
    entry = {"action": action, "actor_id": actor_id, "actor_name": actor_name or "Someone",
             "at": _now()}
    if note:
        entry["note"] = str(note)[:2000]
    pipe["activity"] = (pipe.get("activity") or [])[-49:] + [entry]
    pipe["updated_at"] = _now()
    return pipe


def _sink(shop: str):
    """A ShopifySink for this shop, or a 400 if it isn't a write-back-capable Shopify tenant."""
    tenant = shop_store().get_tenant(shop)
    token = shop_store().get_token(shop)
    if not token or (tenant and tenant["kind"] in ("woocommerce", "bigcommerce", "centra", "scayle")):
        raise HTTPException(400, "The pipeline is available for Shopify stores with write-back enabled.")
    from halia.adapters.shopify_sink import ShopifySink
    from scoring.shopify_fetch import http_transport
    return ShopifySink(transport=http_transport(shop, token))


def _actor(request: Request, payload: dict) -> tuple[str | None, str | None]:
    return current_staff_id(request), (str(payload.get("actor") or "").strip()[:80] or None)


def _cid(payload: dict) -> str:
    cid = str((payload or {}).get("cid") or "").strip()
    if not cid:
        raise HTTPException(422, "cid is required.")
    return cid


def _write(sink, cid: str, pipe: dict) -> None:
    sink.set_metafield(cid, "pipeline", json.dumps(pipe))


def register(app) -> None:

    @app.post("/v1/board/add")
    def board_add(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = _cid(p)
        stage = "To reach out"
        sink = _sink(shop)
        actor_id, actor_name = _actor(request, p)
        pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
        pipe["stage"] = stage
        append_activity(pipe, "added", actor_id, actor_name)
        sink.untag_customer(cid, [stage_tag(s) for s in STAGES if s != stage])
        sink.tag_customer(cid, [stage_tag(stage)])
        _write(sink, cid, pipe)
        return {"ok": True, "pipeline": pipe}

    @app.post("/v1/board/move")
    def board_move(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = _cid(p)
        stage = str(p.get("stage") or "")
        if stage not in STAGES:
            raise HTTPException(422, "Unknown stage.")
        sink = _sink(shop)
        actor_id, actor_name = _actor(request, p)
        pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
        pipe["stage"] = stage
        append_activity(pipe, f"moved:{stage}", actor_id, actor_name)
        sink.untag_customer(cid, [stage_tag(s) for s in STAGES if s != stage])
        sink.tag_customer(cid, [stage_tag(stage)])
        _write(sink, cid, pipe)
        return {"ok": True, "pipeline": pipe}

    @app.post("/v1/board/assign")
    def board_assign(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = _cid(p)
        assignee = {"id": str(p.get("assignee_id") or "").strip() or None,
                    "name": str(p.get("assignee_name") or "").strip()[:80] or None}
        sink = _sink(shop)
        actor_id, actor_name = _actor(request, p)
        pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
        pipe["assignee"] = None if not (assignee["id"] or assignee["name"]) else assignee
        label = (assignee["name"] or "unassigned") if pipe["assignee"] else "unassigned"
        append_activity(pipe, f"assigned:{label}", actor_id, actor_name)
        _write(sink, cid, pipe)
        return {"ok": True, "pipeline": pipe}

    @app.post("/v1/board/note")
    def board_note(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = _cid(p)
        note = str(p.get("note") or "").strip()
        if not note:
            raise HTTPException(422, "note is required.")
        sink = _sink(shop)
        actor_id, actor_name = _actor(request, p)
        pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
        append_activity(pipe, "note", actor_id, actor_name, note=note)
        _write(sink, cid, pipe)
        return {"ok": True, "pipeline": pipe}

    @app.post("/v1/board/remove")
    def board_remove(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = _cid(p)
        sink = _sink(shop)
        actor_id, actor_name = _actor(request, p)
        pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
        pipe["stage"] = None
        append_activity(pipe, "removed", actor_id, actor_name)
        sink.untag_customer(cid, [stage_tag(s) for s in STAGES])
        _write(sink, cid, pipe)
        return {"ok": True}

    @app.get("/v1/board")
    def board_get(shop: str = Depends(require_shop)) -> dict:
        from scoring.shopify_pipeline import fetch_pipeline_cards
        try:
            sink = _sink(shop)
        except HTTPException:
            return {"available": False, "stages": STAGES, "cards": []}
        cards = fetch_pipeline_cards(sink._transport())
        return {"available": True, "stages": STAGES, "cards": list(cards.values())}
