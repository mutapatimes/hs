"""Campaign monitoring API: create/list/delete campaigns and render a campaign's monitor.

Only the campaign config persists (name, dates, target grades/signals + optional opaque member
ids). The monitor is computed live from the shop's RAM-cached book and rendered by
halia.campaign_view, so nothing about customers is stored (zero-retention).
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Any

from fastapi import Body, Depends, HTTPException
from fastapi.responses import HTMLResponse

from halia.api.shopify_auth import require_shop, shop_store
from halia.cache import cache
from halia.campaigns import campaign_metrics
from halia.campaign_view import render_campaign

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _clean_config(raw: Any) -> dict:
    raw = raw or {}
    def _strs(key, upper=False, cap=200):
        vals = raw.get(key) or []
        out = []
        for v in vals if isinstance(vals, list) else []:
            s = str(v).strip()
            if s:
                out.append(s.upper() if upper else s)
        return out[:cap]
    return {"tiers": _strs("tiers", upper=True), "signals": _strs("signals"),
            "members": _strs("members", cap=5000)}   # hand-picked lists can be larger


def _campaign_dict(row: dict) -> dict:
    try:
        cfg = json.loads(row.get("config_json") or "{}")
    except (TypeError, ValueError):
        cfg = {}
    return {"id": row["id"], "name": row["name"], "starts": row["starts"],
            "ends": row["ends"], "config": cfg, "updated_at": row.get("updated_at")}


def register(app) -> None:

    @app.get("/v1/campaigns")
    def list_campaigns(shop: str = Depends(require_shop)) -> dict:
        return {"campaigns": [_campaign_dict(r) for r in shop_store().list_campaigns(shop)]}

    @app.post("/v1/campaigns")
    def save_campaign(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        name = str(p.get("name") or "").strip()[:120]
        starts = str(p.get("starts") or "").strip()
        ends = str(p.get("ends") or "").strip()
        if not name:
            raise HTTPException(400, "Give the campaign a name.")
        if not (_DATE.match(starts) and _DATE.match(ends)):
            raise HTTPException(400, "Set valid start and end dates (YYYY-MM-DD).")
        if ends < starts:
            raise HTTPException(400, "The end date must be on or after the start date.")
        cid = str(p.get("id") or "").strip() or ("camp_" + secrets.token_urlsafe(8))
        # Campaigns are membership-based (added from the Clients tab). Editing name/dates must
        # NOT wipe the members: when the form omits config, preserve the existing one.
        if p.get("config") is not None:
            cfg = _clean_config(p.get("config"))
        else:
            existing = shop_store().get_campaign(cid, shop) if p.get("id") else None
            cfg = (_clean_config(json.loads(existing.get("config_json") or "{}"))
                   if existing else _clean_config({}))
        shop_store().save_campaign(cid, shop, name, starts, ends, json.dumps(cfg))
        return {"ok": True, "id": cid}

    @app.delete("/v1/campaigns/{campaign_id}")
    def delete_campaign(campaign_id: str, shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_campaign(campaign_id, shop)
        return {"ok": True}

    @app.post("/v1/campaigns/{campaign_id}/members")
    def campaign_member(campaign_id: str, shop: str = Depends(require_shop),
                        payload: Any = Body(...)) -> dict:
        """Hand-pick a client into (or out of) a campaign. cid is an opaque customer id."""
        row = shop_store().get_campaign(campaign_id, shop)
        if not row:
            raise HTTPException(404, "Campaign not found.")
        p = payload or {}
        raw = p.get("cids") if isinstance(p.get("cids"), list) else [p.get("cid")]
        targets = {str(x).strip() for x in raw if str(x or "").strip()}
        if not targets:
            raise HTTPException(400, "No client id(s).")
        cfg = _clean_config(json.loads(row.get("config_json") or "{}"))
        members = [m for m in cfg["members"] if m not in targets]     # drop, then re-add (dedup)
        if not p.get("remove"):
            members += sorted(targets)
        cfg["members"] = members
        shop_store().save_campaign(campaign_id, shop, row["name"], row["starts"], row["ends"],
                                   json.dumps(cfg))
        return {"ok": True, "in": not bool(p.get("remove")), "count": len(members),
                "added": len(targets) if not p.get("remove") else 0}

    @app.get("/v1/campaigns/{campaign_id}/monitor", response_class=HTMLResponse)
    def monitor(campaign_id: str, shop: str = Depends(require_shop)) -> HTMLResponse:
        row = shop_store().get_campaign(campaign_id, shop)
        if not row:
            raise HTTPException(404, "Campaign not found.")
        entry = cache.get(shop)
        clients = ((entry or {}).get("payload") or {}).get("data", []) if entry else []
        metrics = campaign_metrics(_campaign_dict(row), clients)
        resp = HTMLResponse(render_campaign(metrics))
        resp.headers["Cache-Control"] = "no-store"
        return resp
