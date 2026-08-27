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
_TTL_SECONDS = 600                   # a built report lives in RAM this long (never on disk)
_REPORT_CACHE: dict[tuple, tuple[float, dict]] = {}


def invalidate(shop: str) -> None:
    """Drop cached reports for a shop (a pipeline move, a contact log, a capture)."""
    for key in [k for k in _REPORT_CACHE if k[0] == shop]:
        _REPORT_CACHE.pop(key, None)

_CAPTURES_QUERY = """
query HaliaCaptures($cursor: String) {
  customers(first: 100, after: $cursor, query: "tag:halia-captured") {
    pageInfo { hasNextPage endCursor }
    nodes { id metafield(namespace: "halia", key: "capture") { value } }
  }
}"""


def fetch_captures(transport, retries: int = 5, max_pages: int = 20) -> list[dict]:
    """Every captured client's consent record ({channel, at, seat_id, associate, ...}) plus the
    customer id, read from the merchant's own metafields. Nothing is stored."""
    import json as _json

    from scoring.shopify_fetch import _run

    if transport is None:
        return []
    out, cursor = [], None
    for _ in range(max_pages):
        data_ = _run(transport, _CAPTURES_QUERY, {"cursor": cursor}, retries)
        conn = (data_ or {}).get("customers") or {}
        for node in conn.get("nodes") or []:
            raw = ((node.get("metafield") or {}).get("value")) or ""
            try:
                rec = _json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                rec = {}
            if isinstance(rec, dict):
                rec["cid"] = str(node.get("id") or "").rsplit("/", 1)[-1]
                out.append(rec)
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        cursor = info.get("endCursor")
    return out


def _day(s: Any) -> str:
    return str(s or "")[:10]


def _parse(s: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def build_report(shop: str, days: int = 30, fresh: bool = False) -> dict:
    import time as _time

    days = max(1, min(int(days or 30), 365))
    hit = _REPORT_CACHE.get((shop, days))
    if hit and not fresh and _time.time() - hit[0] < _TTL_SECONDS:
        return hit[1]
    rep = _build_report(shop, days)
    _REPORT_CACHE[(shop, days)] = (_time.time(), rep)
    return rep


def _build_report(shop: str, days: int) -> dict:
    from halia.api.board import _sink

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        sink = _sink(shop)
    except HTTPException:
        return {"available": False, "days": days, "seats": [], "totals": {}}
    from halia.api.board import pipeline_cards as _cards
    cards = _cards(sink)
    entry = data.results_for(shop) or {}
    payload = entry.get("payload") or {}
    grade_of = {str(r.get("cid")): (r.get("grade") or "") for r in (payload.get("data") or [])}
    orders_by_cid: dict[str, list] = {}
    for o in payload.get("orders") or []:
        orders_by_cid.setdefault(str(o.get("cid")), []).append(o)

    seats, former = {}, set()
    for s in shop_store().list_seats(shop, include_revoked=True):
        gone = bool(s.get("revoked_at"))
        if gone:
            former.add(s["id"])
        seats[s["id"]] = {"id": s["id"], "name": s["name"] + (" (former)" if gone else ""),
                          "title": s.get("title") or "", "email": s.get("email") or "",
                          "former": gone}

    def bucket(actor_id):
        key = actor_id if actor_id in seats else UNATTRIBUTED
        if key not in rows:
            base = seats.get(key) or {"id": UNATTRIBUTED, "name": "Shared sign-in", "title": "", "email": ""}
            rows[key] = {**base, "contacts": 0, "moves": 0, "assigns": 0, "notes": 0,
                         "clients": set(), "owned": 0, "conversions": 0, "revenue": 0,
                         "captures": 0, "captured_top": 0}
        return rows[key]

    rows: dict[str, dict] = {}
    for sid in seats:                     # every current teammate appears, even with a quiet month
        if sid not in former:
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

    # Captures: the clients each associate brought into the book (the handover form, QR, vCard).
    try:
        captures = sink.captures() if hasattr(sink, "captures") else fetch_captures(sink._transport())
    except Exception:  # noqa: BLE001 — the rest of the report still renders
        captures = []
    for rec in captures:
        when = _parse(rec.get("at"))
        if not when or when < cutoff:
            continue
        b = bucket(rec.get("seat_id") or None)
        b["captures"] += 1
        if grade_of.get(str(rec.get("cid"))) in ("A*", "A"):
            b["captured_top"] += 1

    # Conversions: each order goes to the latest contact that preceded it within the window.
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
                       key=lambda r: (r.get("former", False), -r["contacts"], r["name"]))
    unatt = next((r for r in out if r["id"] == UNATTRIBUTED), None)
    if unatt and not any(unatt[k] for k in ("contacts", "moves", "assigns", "notes", "conversions", "captures")):
        unatt = None
    totals = {k: sum(r[k] for r in out)
              for k in ("contacts", "clients", "moves", "conversions", "revenue", "captures", "captured_top")}
    totals["rate"] = round(totals["conversions"] / totals["contacts"], 2) if totals["contacts"] else 0.0
    return {"available": True, "days": days, "window": CONVERSION_WINDOW_DAYS,
            "seats": seat_rows, "unattributed": unatt, "totals": totals}


def register(app) -> None:
    @app.get("/v1/reports/associates")
    def associates(shop: str = Depends(require_shop), days: int = Query(30)) -> dict:
        return build_report(shop, days)


def seat_week(shop: str, seat_id: str, days: int = 7) -> dict:
    """One associate's own numbers for the period (the iPhone desk's "Your week")."""
    rep = build_report(shop, days)
    mine = next((r for r in rep.get("seats") or [] if r.get("id") == seat_id), None)
    return {"available": bool(rep.get("available")), "days": rep.get("days", days),
            "window": rep.get("window", CONVERSION_WINDOW_DAYS),
            "me": mine, "team": rep.get("totals") or {}}

