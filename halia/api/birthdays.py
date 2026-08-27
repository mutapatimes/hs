"""Birthdays, surfaced: the captured ones and any the store keeps on the customer.

Read at view time from the merchant's own metafields (``halia.preferences.birthday`` from
in-store capture, and Shopify's standard ``facts.birth_date`` where a store fills it). Parsed
to a month and day; nothing is stored. The Overview shows who is coming up; the desk and the
"reach today" queue carry them to the associate with the birthday note one tap away.

    GET /v1/birthdays?days=14            (dashboard session)
    GET /v1/extension/birthdays?days=14  (seat token)
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from typing import Any

from fastapi import Depends, Query

from halia.api import data
from halia.api.shopify_auth import get_valid_token, require_shop

_TTL = 600
_CACHE: dict[str, tuple[float, list]] = {}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_CAPTURED = """
query HaliaBirthdays($cursor: String) {
  customers(first: 100, after: $cursor, query: "tag:halia-captured") {
    pageInfo { hasNextPage endCursor }
    nodes { id firstName lastName
      prefs: metafield(namespace: "halia", key: "preferences") { value }
      born: metafield(namespace: "facts", key: "birth_date") { value } }
  }
}"""

_BY_IDS = """
query HaliaBirthdaysByIds($ids: [ID!]!) {
  nodes(ids: $ids) { ... on Customer { id firstName lastName
    born: metafield(namespace: "facts", key: "birth_date") { value } } }
}"""


def parse_birthday(raw: Any) -> tuple[int, int] | None:
    """(month, day) from the ways people write a birthday: 14 June, June 14, 14/06, 2001-06-14."""
    t = str(raw or "").strip().lower()
    if not t:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", t)               # ISO
    if m:
        mo, dd = int(m.group(2)), int(m.group(3))
        return (mo, dd) if 1 <= mo <= 12 and 1 <= dd <= 31 else None
    m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})(?:[/.\-]\d{2,4})?$", t)   # day/month (UK)
    if m:
        dd, mo = int(m.group(1)), int(m.group(2))
        return (mo, dd) if 1 <= mo <= 12 and 1 <= dd <= 31 else None
    words = re.findall(r"[a-z]+|\d+", t)
    mo = next((_MONTHS[w[:3]] for w in words if w[:3] in _MONTHS and w.isalpha()), None)
    dd = next((int(w) for w in words if w.isdigit() and 1 <= int(w) <= 31), None)
    return (mo, dd) if mo and dd else None


def _gql(shop: str, query: str, variables: dict) -> dict:
    from scoring.shopify_fetch import _run, http_transport
    return _run(http_transport(shop, get_valid_token(shop)), query, variables, 3)


def fetch_birthdays(shop: str) -> list[dict]:
    """[{cid, name, month, day, source}] for captured clients and the surfaced book."""
    if not get_valid_token(shop):
        return []
    found: dict[str, dict] = {}

    def take(node, source_pref=True):
        cid = str(node.get("id") or "").rsplit("/", 1)[-1]
        name = " ".join(x for x in (node.get("firstName") or "", node.get("lastName") or "") if x).strip()
        bday = None
        prefs = ((node.get("prefs") or {}) or {}).get("value") if node.get("prefs") else None
        if prefs:
            try:
                bday = parse_birthday((json.loads(prefs) or {}).get("birthday"))
            except (TypeError, ValueError):
                bday = None
        src = "captured"
        if not bday and node.get("born") and (node["born"] or {}).get("value"):
            bday, src = parse_birthday(node["born"]["value"]), "store"
        if bday and cid:
            found[cid] = {"cid": cid, "name": name or "A client", "month": bday[0], "day": bday[1], "source": src}

    cursor = None
    for _ in range(20):
        d = _gql(shop, _CAPTURED, {"cursor": cursor})
        conn = (d or {}).get("customers") or {}
        for n in conn.get("nodes") or []:
            take(n)
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        cursor = info.get("endCursor")

    # The surfaced book may carry the store's own birth dates (Shopify's facts.birth_date).
    entry = data.results_for(shop) or {}
    cids = [str(r.get("cid")) for r in ((entry.get("payload") or {}).get("data") or [])
            if r.get("cid") and str(r.get("cid")) not in found][:500]
    for i in range(0, len(cids), 250):
        ids = [f"gid://shopify/Customer/{c}" for c in cids[i:i + 250]]
        try:
            d = _gql(shop, _BY_IDS, {"ids": ids})
        except Exception:  # noqa: BLE001
            break
        for n in (d or {}).get("nodes") or []:
            if n:
                take(n)
    return list(found.values())


def upcoming(shop: str, days: int = 14, today: date | None = None) -> list[dict]:
    """Birthdays in the next ``days`` days, soonest first, with the grade from the warm book."""
    days = max(1, min(int(days or 14), 90))
    hit = _CACHE.get(shop)
    rows = hit[1] if hit and time.time() - hit[0] < _TTL else None
    if rows is None:
        rows = fetch_birthdays(shop)
        _CACHE[shop] = (time.time(), rows)
    today = today or date.today()
    entry = data.results_for(shop) or {}
    grade_of = {str(r.get("cid")): (r.get("grade") or "") for r in ((entry.get("payload") or {}).get("data") or [])}
    out = []
    for r in rows:
        try:
            nxt = date(today.year, r["month"], r["day"])
        except ValueError:
            continue
        if nxt < today:
            try:
                nxt = date(today.year + 1, r["month"], r["day"])
            except ValueError:
                continue
        delta = (nxt - today).days
        if delta <= days:
            out.append({**r, "date": nxt.isoformat(), "in_days": delta, "grade": grade_of.get(r["cid"], "")})
    out.sort(key=lambda x: (x["in_days"], x["name"]))
    return out


def invalidate(shop: str) -> None:
    _CACHE.pop(shop, None)


def register(app) -> None:
    @app.get("/v1/birthdays")
    def birthdays(shop: str = Depends(require_shop), days: int = Query(14)) -> dict:
        rows = upcoming(shop, days)
        return {"days": max(1, min(int(days or 14), 90)), "count": len(rows), "birthdays": rows}
