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

from halia.api.shopify_auth import current_staff_id, get_valid_token, require_shop, shop_store
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
    pipe.setdefault("due", None)
    pipe.setdefault("appointments", [])
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
    """The write-back sink for this shop: Shopify (tags + metafields) or WooCommerce (customer
    meta + an opaque-id index). 400 for platforms without write-back yet."""
    tenant = dict(shop_store().get_tenant(shop) or {})
    kind = tenant.get("kind")
    if kind == "woocommerce":
        return woo_sink(shop)
    token = get_valid_token(shop)
    if not token or kind in ("bigcommerce", "centra", "scayle"):
        raise HTTPException(400, "The pipeline is available for Shopify and WooCommerce stores with write-back enabled.")
    from halia.adapters.shopify_sink import ShopifySink
    from scoring.shopify_fetch import http_transport
    return ShopifySink(transport=http_transport(shop, token))


def woo_sink(shop: str):
    """A WooSink bound to this tenant's stored REST credentials and its id index."""
    from halia.adapters.woo_sink import WooClient, WooSink
    creds = shop_store().get_woocommerce(shop)
    if not creds:
        raise HTTPException(400, "Connect WooCommerce with a read/write key to use the pipeline.")
    st = shop_store()
    return WooSink(WooClient(creds["store_url"], creds["consumer_key"], creds["consumer_secret"]),
                   index_add=lambda kind, cid: st.woo_index_add(shop, kind, cid),
                   index_remove=lambda kind, cid: st.woo_index_remove(shop, kind, cid),
                   index_list=lambda kind: st.woo_index_list(shop, kind))


def pipeline_cards(sink) -> dict:
    """Every carded customer, whichever platform the sink speaks."""
    if hasattr(sink, "pipeline_cards"):
        return sink.pipeline_cards()
    from scoring.shopify_pipeline import fetch_pipeline_cards
    return fetch_pipeline_cards(sink._transport())


def _actor(request: Request, payload: dict) -> tuple[str | None, str | None]:
    """Who is acting, as a seat when we know one: the Shopify staff user's mapped seat, else the
    seat this browser chose (hosted dashboards), else the typed name from before seats existed."""
    staff = current_staff_id(request)
    shop = _shop_of(request)
    seat = None
    if staff and shop:
        seat = shop_store().seat_for_staff(shop, staff)
    if not seat and shop and str(payload.get("seat_id") or "").strip():
        seat = shop_store().seat_profile(str(payload.get("seat_id")).strip())
        if seat and seat.get("shop") != shop:
            seat = None
    if seat:
        return seat["id"], (seat.get("name") or None)
    return staff, (str(payload.get("actor") or "").strip()[:80] or None)


def _reports_invalidate(shop: str) -> None:
    try:
        from halia.api import reports
        reports.invalidate(shop)
    except Exception:  # noqa: BLE001
        pass


def _shop_of(request: Request) -> str | None:
    try:
        from halia.api.shopify_auth import require_shop
        return require_shop(request)
    except Exception:  # noqa: BLE001
        return None


def _cid(payload: dict) -> str:
    cid = str((payload or {}).get("cid") or "").strip()
    if not cid:
        raise HTTPException(422, "cid is required.")
    return cid


def _write(sink, cid: str, pipe: dict) -> None:
    sink.set_metafield(cid, "pipeline", json.dumps(pipe))


def _write_soft(sink, cid: str, pipe: dict) -> str | None:
    """Persist the activity/assignee metafield, best-effort. The card's STAGE lives in the customer
    tag (written separately and the board's source of truth), so a metafield hiccup must not fail
    the whole move — otherwise the tag change sticks but the request 500s and the UI shows an error
    even though the move happened. Returns an error string on failure (logged), else None."""
    try:
        _write(sink, cid, pipe)
        return None
    except Exception as exc:  # noqa: BLE001 — metafield is supplementary; never break the move
        import logging
        logging.getLogger("halia.board").warning("pipeline metafield write failed for %s: %s", cid, exc)
        return str(exc)


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
        warn = _write_soft(sink, cid, pipe)
        _reports_invalidate(shop)
        return {"ok": True, "pipeline": pipe, "warning": warn}

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
        warn = _write_soft(sink, cid, pipe)
        _reports_invalidate(shop)
        return {"ok": True, "pipeline": pipe, "warning": warn}

    @app.get("/v1/me")
    def me(request: Request, shop: str = Depends(require_shop)) -> dict:
        """Who this dashboard user is (as a seat), plus the seats to choose from. A Shopify staff
        user is remembered server-side; a hosted dashboard keeps its choice in the browser and
        passes ?seat_id= to confirm it."""
        staff = current_staff_id(request)
        seat = shop_store().seat_for_staff(shop, staff) if staff else None
        chosen = str(request.query_params.get("seat_id") or "").strip()
        if not seat and chosen:
            prof = shop_store().seat_profile(chosen)
            if prof and prof.get("shop") == shop:
                seat = {k: prof.get(k) for k in ("id", "name", "email", "title")}
        seats = [{"id": s["id"], "name": s["name"], "email": s.get("email") or "",
                  "title": s.get("title") or ""} for s in shop_store().list_seats(shop)]
        return {"staff_id": staff, "seat": seat, "seats": seats}

    @app.post("/v1/me")
    def me_choose(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        """This user is that seat. Remembered per Shopify staff user; hosted dashboards just get
        the validated seat back to keep in the browser."""
        seat_id = str((payload or {}).get("seat_id") or "").strip()
        prof = shop_store().seat_profile(seat_id) if seat_id else None
        if not prof or prof.get("shop") != shop:
            raise HTTPException(422, "Pick a teammate with a live seat.")
        staff = current_staff_id(request)
        if staff:
            shop_store().map_staff_seat(shop, staff, seat_id)
        return {"ok": True, "seat": {k: prof.get(k) for k in ("id", "name", "email", "title")},
                "remembered": bool(staff)}

    @app.post("/v1/board/assign")
    def board_assign(request: Request, shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        cid = _cid(p)
        assignee = {"id": str(p.get("assignee_id") or "").strip() or None,
                    "name": str(p.get("assignee_name") or "").strip()[:80] or None}
        # Assigning to a seat: the id and name come from the seat record, so the card and the
        # future per-associate report agree on who owns the client.
        seat_id = str(p.get("assignee_seat") or "").strip()
        if seat_id:
            seat = shop_store().seat_profile(seat_id)
            if not seat or seat.get("shop") != shop:
                raise HTTPException(422, "That teammate has no live seat here.")
            assignee = {"id": seat["id"], "name": seat.get("name") or None}
        sink = _sink(shop)
        actor_id, actor_name = _actor(request, p)
        pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
        pipe["assignee"] = None if not (assignee["id"] or assignee["name"]) else assignee
        label = (assignee["name"] or "unassigned") if pipe["assignee"] else "unassigned"
        append_activity(pipe, f"assigned:{label}", actor_id, actor_name)
        _reports_invalidate(shop)
        if _write_soft(sink, cid, pipe):
            raise HTTPException(502, "Could not save to Shopify just now. Please try again.")
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
        _reports_invalidate(shop)
        if _write_soft(sink, cid, pipe):
            raise HTTPException(502, "Could not save to Shopify just now. Please try again.")
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
        _write_soft(sink, cid, pipe)
        return {"ok": True}

    @app.get("/v1/board")
    def board_get(shop: str = Depends(require_shop)) -> dict:
        try:
            sink = _sink(shop)
        except HTTPException:
            return {"available": False, "stages": STAGES, "cards": []}
        cards = pipeline_cards(sink)
        return {"available": True, "stages": STAGES, "cards": list(cards.values())}
