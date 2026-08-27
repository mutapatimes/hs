"""Team reporting: what each associate did, and what came of it.

Folded at view time from the merchant's own data: pipeline activity (the ``halia.pipeline``
metafield per client, each entry stamped with the acting seat), the orders already in the warm
book, and the seat list. Nothing is stored; the numbers are recomputed on every request.

    GET /v1/reports/associates?days=30 (auth: dashboard session)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Query

from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store
from scoring.shopify_pipeline import fetch_pipeline_cards

CONVERSION_WINDOW_DAYS = 14          # an order within this many days of a contact counts
UNATTRIBUTED = "unattributed"


def _day(s: Any) -> str:
    return str(s or "")[:10]


def _parse(s: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def build_report(shop: str, days: int = 30) -> dict:
    from halia.api.board import _sink

    days = max(1, min(int(days or 30), 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        sink = _sink(shop)
    except HTTPException:
        return {"available": False, "days": days, "seats": [], "totals": {}}
    cards = fetch_pipeline_cards(sink._transport())
    entry = data.results_for(shop) or {}
    payload = entry.get("payload") or {}
    grade_of = {str(r.get("cid")): (r.get("grade") or "") for r in (payload.get("data") or [])}
    orders_by_cid: dict[str, list] = {}
    for o in payload.get("orders") or []:
        orders_by_cid.setdefault(str(o.get("cid")), []).append(o)

    seats = {s["id"]: {"id": s["id"], "name": s["name"], "title": s.get("title") or "",
                       "email": s.get("email") or ""} for s in shop_store().list_seats(shop)}

    def bucket(actor_id):
        key = actor_id if actor_id in seats else UNATTRIBUTED
        if key not in rows:
            base = seats.get(key) or {"id": UNATTRIBUTED, "name": "Shared sign-in", "title": "", "email": ""}
            rows[key] = {**base, "contacts": 0, "moves": 0, "assigns": 0, "notes": 0,
                         "clients": set(), "owned": 0, "conversions": 0, "revenue": 0}
        return rows[key]

    rows: dict[str, dict] = {}
    for sid in seats:                     # every teammate appears, even with a quiet month
        bucket(sid)
    contacts: list[tuple[str, datetime, str]] = []   # (cid, when, actor bucket key)

    for card in cards.values():
        cid = str(card.get("cid"))
        owner = ((card.get("assignee") or {}).get("id")) or None
        if owner in seats:
            bucket(owner)["owned"] += 1
        for act in card.get("activity") or []:
            when = _parse(act.get("at"))
            if not when or when < cutoff:
                continue
            b = bucket(act.get("actor_id"))
            action = str(act.get("action") or "")
            if action == "contacted":
                b["contacts"] += 1
                b["clients"].add(cid)
                contacts.append((cid, when, b["id"]))
            elif action.startswith("moved:"):
                b["moves"] += 1
            elif action.startswith("assigned:"):
                b["assigns"] += 1
            elif action == "note":
                b["notes"] += 1

    # Conversions: each order goes to the latest contact that preceded it within the window.
    for cid, when, key in contacts:
        pass
    credited: set = set()
    for cid, olist in orders_by_cid.items():
        mine = [(when, key) for (c, when, key) in contacts if c == cid]
        if not mine:
            continue
        for o in olist:
            od = _parse(_day(o.get("date")) + "T23:59:59+00:00")
            if not od or od < cutoff:
                continue
            prior = [(when, key) for (when, key) in mine
                     if when <= od <= when + timedelta(days=CONVERSION_WINDOW_DAYS)]
            if not prior or (cid, o.get("orderId")) in credited:
                continue
            _, key = max(prior, key=lambda x: x[0])
            credited.add((cid, o.get("orderId")))
            rows[key]["conversions"] += 1
            rows[key]["revenue"] += int(o.get("amount") or 0)

    out = []
    for key, r in rows.items():
        clients = r.pop("clients")
        top = sum(1 for c in clients if grade_of.get(c) in ("A*", "A"))
        r["clients"] = len(clients)
        r["topShare"] = round(top / len(clients), 2) if clients else 0.0
        r["rate"] = round(r["conversions"] / r["contacts"], 2) if r["contacts"] else 0.0
        out.append(r)
    seat_rows = sorted([r for r in out if r["id"] != UNATTRIBUTED],
                       key=lambda r: (-r["contacts"], r["name"]))
    unatt = next((r for r in out if r["id"] == UNATTRIBUTED), None)
    if unatt and not any(unatt[k] for k in ("contacts", "moves", "assigns", "notes", "conversions")):
        unatt = None
    totals = {k: sum(r[k] for r in out) for k in ("contacts", "clients", "moves", "conversions", "revenue")}
    totals["rate"] = round(totals["conversions"] / totals["contacts"], 2) if totals["contacts"] else 0.0
    return {"available": True, "days": days, "window": CONVERSION_WINDOW_DAYS,
            "seats": seat_rows, "unattributed": unatt, "totals": totals}


def register(app) -> None:
    @app.get("/v1/reports/associates")
    def associates(shop: str = Depends(require_shop), days: int = Query(30)) -> dict:
        return build_report(shop, days)
