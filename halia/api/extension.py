"""Browser-extension API: a per-merchant token plus a single-customer grade lookup.

The Halia badge extension (see the extension/ directory) puts a client's grade into the surfaces
an associate already works in: the store admin, WhatsApp Web, Gmail. It authenticates with a
long-lived per-tenant token (minted here, shown once in Settings) and asks this endpoint for one
customer's grade at a time.

Zero-retention is untouched. The lookup reads the shop's existing RAM cache (the same warm scored
book the dashboard uses), or scores a single customer live, and stores nothing about the customer.
Only the sha256 hash of the token is persisted, exactly like the self-service tenant link token.

    POST /v1/extension/token   — mint (or rotate) this tenant's extension token (require_shop)
    GET  /v1/extension/token   — whether a token exists, and the API base (require_shop)
    POST /v1/extension/lookup  — one customer's grade, authed by the X-Halia-Ext-Token header
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Depends, Header, HTTPException

from halia import config
from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store
from halia.api.tenant_auth import hash_token, new_token


# ── the "play" a client falls into, mirrored from playOf() in web/template.html ──────
_PLAY = {
    "sleeping": {"label": "Gone quiet",
                 "action": "A proven client who has gone quiet. Reach out personally to bring them back."},
    "fresh": {"label": "Fresh",
              "action": "A new potential VIC. Welcome them personally and lead with service."},
    "": {"label": "", "action": ""},
}


def _play_of(row: dict) -> str:
    tier, band = row.get("tier"), row.get("band")
    if row.get("known") or (tier in ("A1", "A") and (row.get("ordersCount") or 0) >= 2
                            and band == "lapsed"):
        return "sleeping"
    if not row.get("known") and band in ("active", "new"):
        return "fresh"
    return ""


def _templates(shop: str, first_name: str) -> list[dict]:
    """The merchant's own editable outreach templates, with placeholders filled for this client."""
    from halia.api.settings import settings_for
    s = settings_for(shop)
    sender = s.get("sender_name") or ""
    first = first_name or "there"

    def fill(t: str) -> str:
        return (t or "").replace("{first_name}", first).replace("{sender}", sender)

    out = []
    for t in (s.get("email_templates") or [])[:8]:
        out.append({"name": t.get("name", ""), "subject": fill(t.get("subject", "")),
                    "body": fill(t.get("body", ""))})
    return out


def _dashboard_link() -> str:
    return (config.HALIA_APP_URL or "").rstrip("/") + "/app"


def _catalog_link(shop: str) -> Optional[str]:
    from halia.api.catalog import catalog_url_for
    try:
        return catalog_url_for(shop) or None
    except Exception:
        return None


def _cart(row: dict) -> Optional[dict]:
    """A compact open-basket (abandoned checkout), if the client has one, for the badge."""
    c = row.get("cart")
    if not isinstance(c, dict) or not (c.get("value") or 0) > 0:
        return None
    return {"value": c.get("value"), "count": c.get("count"), "url": c.get("url")}


def _resp_from_row(shop: str, row: dict) -> dict:
    """The lookup response built from a warm payload client row (has latent, reasons, reco)."""
    play = _play_of(row)
    first = (row.get("name") or "").split(" ")[0]
    return {
        "found": True,
        "name": row.get("name"),
        "email": row.get("email"),
        "grade": row.get("grade"),
        "tier": row.get("tier"),
        "score": row.get("score"),
        "band": row.get("band"),
        "hidden": not row.get("known"),
        "latent": row.get("latent"),
        "spend": row.get("spend"),
        "ordersCount": row.get("ordersCount"),
        "last": row.get("last"),
        "cart": _cart(row),
        "reasons": [s.get("d") for s in (row.get("signals") or []) if s.get("d")],
        "reco": row.get("reco"),
        "play": play,
        "playLabel": _PLAY[play]["label"],
        "action": _PLAY[play]["action"] or row.get("reco"),
        "adminUrl": row.get("adminUrl"),
        "dashboard": _dashboard_link(),
        "catalog": _catalog_link(shop),
        "templates": _templates(shop, first),
    }


def _resp_from_result(shop: str, r) -> dict:
    """The lookup response for a single customer scored live on a cold-cache miss."""
    reasons = [x.strip() for x in (r.reasons or "").replace(";", "\n").split("\n") if x.strip()]
    return {
        "found": True,
        "name": None,
        "email": r.email,
        "grade": r.grade,
        "tier": r.tier,
        "score": r.score,
        "band": None,
        "hidden": bool(r.hidden_vic),
        "latent": None,
        "spend": r.spend,
        "ordersCount": None,
        "last": None,
        "cart": None,
        "reasons": reasons,
        "reco": r.gesture,
        "play": "",
        "playLabel": "",
        "action": r.gesture,
        "adminUrl": None,
        "dashboard": _dashboard_link(),
        "catalog": _catalog_link(shop),
        "templates": _templates(shop, ""),
    }


def _digits(v: str) -> str:
    """The trailing national digits of a phone, so +44 20 7... and 020 7... compare equal."""
    d = "".join(ch for ch in str(v or "") if ch.isdigit())
    return d[-9:] if len(d) >= 9 else d


def _best(rows: list, pred) -> Optional[dict]:
    best = None
    for r in rows:
        if pred(r) and (best is None or (r.get("score") or 0) > (best.get("score") or 0)):
            best = r
    return best


def _row_match(entry: Optional[dict], email: Optional[str], cid: Optional[str],
               phone: Optional[str] = None, name: Optional[str] = None) -> Optional[dict]:
    """Find a customer in the warm payload by id, email, phone, then (last resort) exact name."""
    rows = ((entry or {}).get("payload") or {}).get("data") or []
    if cid:
        num = str(cid).rsplit("/", 1)[-1]
        forms = {str(cid), num, f"gid://shopify/Customer/{num}"}
        for r in rows:
            if str(r.get("cid")) in forms:
                return r
    if email:
        el = email.lower()
        hit = _best(rows, lambda r: (r.get("email") or "").lower() == el)
        if hit:
            return hit
    if phone:
        pd = _digits(phone)
        if len(pd) >= 7:
            hit = _best(rows, lambda r: _digits(r.get("phone")) == pd)
            if hit:
                return hit
    if name:
        nl = name.strip().lower()
        if nl:
            return _best(rows, lambda r: (r.get("name") or "").strip().lower() == nl)
    return None


def _lookup(shop: str, email: Optional[str], cid: Optional[str],
            phone: Optional[str] = None, name: Optional[str] = None) -> dict:
    from halia.api.app import _pos_live
    from halia.cache import cache

    entry = cache.get(shop)                     # warm path first — never blocks on a sync
    row = _row_match(entry, email, cid, phone, name)
    if row is None and entry is None:           # cold cache: sync once, then match warm
        entry = data.results_for(shop)
        row = _row_match(entry, email, cid, phone, name)
    if row is not None:
        return _resp_from_row(shop, row)
    # Not a flagged client in the book. On a Shopify tenant, score just this one customer live by
    # id or email — they may be new since the last sync. Only surface a genuine hidden VIC.
    r = _pos_live(shop, cid, email) if (cid or email) else None
    if r is not None and getattr(r, "matched", True) and (r.hidden_vic or r.is_priority):
        return _resp_from_result(shop, r)
    return {"found": False}


def register(app) -> None:

    @app.post("/v1/extension/token")
    def mint_extension_token(shop: str = Depends(require_shop)) -> dict:
        token = new_token()
        shop_store().set_extension_token(shop, hash_token(token))
        return {"token": token, "base": (config.HALIA_APP_URL or "").rstrip("/")}

    @app.get("/v1/extension/token")
    def extension_token_status(shop: str = Depends(require_shop)) -> dict:
        return {"enabled": bool(shop_store().get_extension_token_hash(shop)),
                "base": (config.HALIA_APP_URL or "").rstrip("/")}

    @app.post("/v1/extension/lookup")
    def extension_lookup(x_halia_ext_token: Optional[str] = Header(None),
                         payload: Any = Body(default=None)) -> dict:
        token_hash = hash_token(x_halia_ext_token) if x_halia_ext_token else ""
        shop = shop_store().shop_for_extension_token(token_hash) if token_hash else None
        if not shop:
            raise HTTPException(401, "Invalid or missing extension token")
        body = payload or {}
        email = (str(body.get("email") or "").strip()) or None
        cid = (str(body.get("cid") or body.get("customer_id") or "").strip()) or None
        phone = (str(body.get("phone") or "").strip()) or None
        name = (str(body.get("name") or "").strip()) or None
        if not (email or cid or phone or name):
            raise HTTPException(422, "Provide email, cid, phone or name")
        data.record_activity(shop, "extension_lookup")
        return _lookup(shop, email, cid, phone, name)
