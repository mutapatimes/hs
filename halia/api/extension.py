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

from fastapi import Body, Depends, Header, HTTPException, Query

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


def _fill(text: str, first, sender: str, catalog) -> str:
    """Fill template tokens. first=None leaves {first_name} for the toolbar to fill per client."""
    t = text or ""
    if first is not None:
        t = t.replace("{first_name}", first or "there")
    t = t.replace("{sender}", sender or "")
    if catalog:
        t = t.replace("{catalog_link}", catalog)
    return t


def _templates(shop: str, first_name, catalog=None) -> list[dict]:
    """The merchant's own editable outreach templates, with placeholders filled for this client."""
    from halia.api.settings import settings_for
    s = settings_for(shop)
    sender = s.get("sender_name") or ""
    cat = catalog if catalog is not None else _catalog_link(shop)
    out = []
    for t in (s.get("email_templates") or [])[:12]:
        out.append({"name": t.get("name", ""),
                    "subject": _fill(t.get("subject", ""), first_name, sender, cat),
                    "body": _fill(t.get("body", ""), first_name, sender, cat)})
    return out


def _dashboard_link() -> str:
    return (config.HALIA_APP_URL or "").rstrip("/") + "/app"


def _last_outreach(activity: list) -> Optional[dict]:
    """The most recent outreach (contacted / note) from a pipeline activity log, so the toolbar can
    warn 'already contacted' before someone messages again. None if the client has never been touched."""
    last = None
    for a in activity or []:
        if a.get("action") in ("contacted", "note"):
            if last is None or (a.get("at") or "") > (last.get("at") or ""):
                last = a
    if not last:
        return None
    return {"at": last.get("at"), "by": last.get("actor_name"),
            "action": last.get("action"), "note": last.get("note")}


def _todos(shop: str) -> list[dict]:
    """Team to-dos from the scored book: fresh orders from top clients to acknowledge, and proven
    clients gone quiet to win back. Warm cache only, so this is cheap. No customer data stored."""
    import time
    from halia.cache import cache
    rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []
    now = time.time()
    out = []
    for r in rows:
        name = r.get("name") or "A client"
        grade = r.get("grade") or ""
        ls = r.get("lastSort") or 0
        recent = ls and (now - ls) <= 7 * 86400
        top = str(r.get("tier") or "").startswith("A")
        if top and r.get("band") == "active" and recent:
            out.append({"kind": "new_order", "cid": r.get("cid"), "name": name, "grade": grade,
                        "text": f"New order · {name} ({grade}) · send a personal note"})
        elif _play_of(r) == "sleeping":
            out.append({"kind": "gone_quiet", "cid": r.get("cid"), "name": name, "grade": grade,
                        "text": f"Gone quiet · {name} ({grade}) · reach out"})
    out.sort(key=lambda t: 0 if t["kind"] == "new_order" else 1)
    return out[:15]


def _cart_base(shop: str) -> str:
    """The storefront origin for a Shopify /cart permalink: the primary domain, else myshopify."""
    dom = ""
    try:
        from halia.api.catalog import _primary_domain
        dom = _primary_domain(shop) or ""
    except Exception:
        dom = ""
    if not dom:
        dom = shop if shop.endswith(".myshopify.com") else f"{shop}.myshopify.com"
    return "https://" + dom


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
        "cid": row.get("cid"),
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
        "cid": getattr(r, "customer_id", None),
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

    @app.get("/v1/extension/context")
    def extension_context(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """The toolbar's standing context, independent of any one client: the merchant's templates,
        their live catalogue, and the campaigns running now. Refreshed by the extension so the
        toolbar is always ready. No customer data."""
        import json
        from datetime import date, timezone, datetime

        from halia.api.campaigns import _utm_slug
        from halia.api.settings import settings_for

        token_hash = hash_token(x_halia_ext_token) if x_halia_ext_token else ""
        shop = shop_store().shop_for_extension_token(token_hash) if token_hash else None
        if not shop:
            raise HTTPException(401, "Invalid or missing extension token")
        s = settings_for(shop)
        catalog = _catalog_link(shop)
        today = datetime.now(timezone.utc).date().isoformat()
        campaigns = []
        for row in shop_store().list_campaigns(shop):
            try:
                cfg = json.loads(row.get("config_json") or "{}")
            except (TypeError, ValueError):
                cfg = {}
            starts, ends = row.get("starts") or "", row.get("ends") or ""
            campaigns.append({
                "id": row["id"], "name": row["name"], "starts": starts, "ends": ends,
                "running": bool(starts <= today <= ends) if (starts and ends) else False,
                "members": len((cfg.get("members") or [])),
                "utm": (cfg.get("utm") or {}).get("campaign") or _utm_slug(row["name"]) or row["id"],
            })
        campaigns.sort(key=lambda c: (not c["running"], c["starts"] or ""))
        tenant = dict(shop_store().get_tenant(shop) or {})
        return {
            "label": tenant.get("label") or shop,
            "platform": tenant.get("kind") or ("shopify" if shop.endswith(".myshopify.com") else "shopify"),
            "brand": s.get("brand") or "halia",
            "catalog": catalog,
            "dashboard": _dashboard_link(),
            "templates": _templates(shop, None, catalog),
            "campaigns": campaigns,
            "todos": _todos(shop),
            "slack": bool(shop_store().get_slack(shop)),   # team broadcasts available?
        }

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

    @app.get("/v1/extension/history")
    def extension_history(x_halia_ext_token: Optional[str] = Header(None),
                          cid: str = Query("")) -> dict:
        """The client's last outreach from the shared pipeline log, so the toolbar can flag
        'already contacted' before anyone messages again. Shopify only (the log lives in the
        merchant's own customer metafield). Reads live; stores nothing."""
        token_hash = hash_token(x_halia_ext_token) if x_halia_ext_token else ""
        shop = shop_store().shop_for_extension_token(token_hash) if token_hash else None
        if not shop:
            raise HTTPException(401, "Invalid or missing extension token")
        cid = (cid or "").strip()
        if not cid:
            return {"last_contact": None}
        try:
            from halia.api.board import _sink, load_pipe
            pipe = load_pipe(_sink(shop).get_metafield(cid, "pipeline"))
        except Exception:
            return {"last_contact": None}            # non-Shopify tenant, or no metafield yet
        return {"last_contact": _last_outreach(pipe.get("activity"))}

    @app.get("/v1/extension/products")
    def extension_products(x_halia_ext_token: Optional[str] = Header(None),
                           q: Optional[str] = Query(None),
                           limit: int = Query(20)) -> dict:
        """Search the merchant's Shopify products (with buyable variant ids) so the toolbar can build
        a cart permalink for a client. Shopify-only; returns the storefront base for the /cart link.
        Products are the merchant's own catalogue, not customer data."""
        token_hash = hash_token(x_halia_ext_token) if x_halia_ext_token else ""
        shop = shop_store().shop_for_extension_token(token_hash) if token_hash else None
        if not shop:
            raise HTTPException(401, "Invalid or missing extension token")
        token = shop_store().get_token(shop)
        if not token:                                # non-Shopify or read-only: no cart builder
            return {"products": [], "cart_base": None}
        from scoring.shopify_fetch import _run, http_transport
        from scoring.shopify_graphql import PRODUCT_SEARCH_QUERY, product_search_node
        n = max(1, min(int(limit or 20), 30))
        term = (q or "").strip()[:80]
        try:
            data_ = _run(http_transport(shop, token), PRODUCT_SEARCH_QUERY, {"q": term, "n": n}, 2)
        except Exception:
            return {"products": [], "cart_base": _cart_base(shop)}
        nodes = ((data_.get("products") or {}).get("nodes")) or []
        products = [p for p in (product_search_node(x) for x in nodes) if p["variants"]]
        return {"products": products, "cart_base": _cart_base(shop)}

    @app.post("/v1/extension/batch")
    def extension_batch(x_halia_ext_token: Optional[str] = Header(None),
                        payload: Any = Body(default=None)) -> dict:
        """Grade many customers at once by email, for the inbox-list triage dots. Warm cache only:
        a batch must be cheap, so it never triggers a sync (unknown emails simply return nothing).
        Returns only grade/tier/play per found email. No customer data is stored."""
        from halia.cache import cache

        token_hash = hash_token(x_halia_ext_token) if x_halia_ext_token else ""
        shop = shop_store().shop_for_extension_token(token_hash) if token_hash else None
        if not shop:
            raise HTTPException(401, "Invalid or missing extension token")
        body = payload or {}
        emails = [str(e).strip().lower() for e in (body.get("emails") or []) if str(e).strip()][:100]
        if not emails:
            return {"grades": {}}
        rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []
        idx: dict = {}
        for r in rows:
            em = (r.get("email") or "").lower()
            if em and (em not in idx or (r.get("score") or 0) > (idx[em].get("score") or 0)):
                idx[em] = r
        out = {}
        for em in set(emails):
            r = idx.get(em)
            if r:
                out[em] = {"grade": r.get("grade"), "tier": r.get("tier"),
                           "hidden": not r.get("known"), "play": _play_of(r)}
        return {"grades": out}

    @app.post("/v1/extension/action")
    def extension_action(x_halia_ext_token: Optional[str] = Header(None),
                         payload: Any = Body(default=None)) -> dict:
        """Take a one-click clienteling action on a client from the toolbar. Both actions preserve
        zero-retention: 'pipeline' writes a stage tag + metafield into the merchant's own Shopify;
        'campaign_add' stores an opaque customer id in the campaign config (as the dashboard does)."""
        import json as _json

        token_hash = hash_token(x_halia_ext_token) if x_halia_ext_token else ""
        shop = shop_store().shop_for_extension_token(token_hash) if token_hash else None
        if not shop:
            raise HTTPException(401, "Invalid or missing extension token")
        body = payload or {}
        action = str(body.get("action") or "").strip()
        cid = str(body.get("cid") or "").strip()
        if not cid:
            raise HTTPException(422, "cid is required")

        who = str(body.get("actor") or "").strip()[:80] or "A team member"

        if action == "contacted":
            # Log that this client was reached out to, so the team is in the loop and nobody
            # double-messages. Records to the shared pipeline activity (Shopify) AND broadcasts to
            # the team's Slack if connected. Best-effort on each side; at least one should land.
            reason = str(body.get("reason") or "").strip()[:200]
            client_name = str(body.get("client_name") or "").strip()[:120]
            recorded = False
            try:
                from halia.api.board import _sink, _write_soft, append_activity, load_pipe
                sink = _sink(shop)
                pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
                append_activity(pipe, "contacted", None, who, note=reason or None)
                recorded = not _write_soft(sink, cid, pipe)
            except Exception:
                recorded = False                     # non-Shopify tenant or write hiccup
            slacked = False
            conn = shop_store().get_slack(shop)
            if conn and conn.get("webhook_url"):
                from halia import notify
                txt = f"{who} contacted {client_name or 'a client'}" + (f" — {reason}" if reason else "")
                try:
                    slacked = bool(notify.send_slack(conn["webhook_url"], txt))
                except Exception:
                    slacked = False
            data.record_activity(shop, "extension_contacted")
            return {"ok": True, "recorded": recorded, "slack": slacked}

        if action == "note":
            from halia.api.board import _sink, _write_soft, append_activity, load_pipe
            note = str(body.get("note") or "").strip()
            if not note:
                raise HTTPException(422, "note is required")
            sink = _sink(shop)                       # 400 if not a Shopify write-back tenant
            pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
            append_activity(pipe, "note", None, who, note=note)
            if _write_soft(sink, cid, pipe):
                raise HTTPException(502, "Could not save to Shopify just now. Please try again.")
            data.record_activity(shop, "extension_note")
            return {"ok": True}

        if action == "pipeline":
            from halia.api.board import _sink, _write_soft, append_activity, load_pipe
            from scoring.shopify_pipeline import STAGES, stage_tag
            sink = _sink(shop)                       # 400 if not a Shopify write-back tenant
            stage = "To reach out"
            pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
            pipe["stage"] = stage
            append_activity(pipe, "added", None, who)
            sink.untag_customer(cid, [stage_tag(s) for s in STAGES if s != stage])
            sink.tag_customer(cid, [stage_tag(stage)])
            _write_soft(sink, cid, pipe)
            data.record_activity(shop, "extension_pipeline_add")
            return {"ok": True, "stage": stage}

        if action == "campaign_add":
            from halia.api.campaigns import _clean_config
            campaign_id = str(body.get("campaign_id") or "").strip()
            if not campaign_id:
                raise HTTPException(422, "campaign_id is required")
            row = shop_store().get_campaign(campaign_id, shop)
            if not row:
                raise HTTPException(404, "Campaign not found")
            cfg = _clean_config(_json.loads(row.get("config_json") or "{}"))
            if cid not in cfg["members"]:
                cfg["members"] = cfg["members"] + [cid]
            shop_store().save_campaign(campaign_id, shop, row["name"], row["starts"], row["ends"],
                                       _json.dumps(cfg))
            data.record_activity(shop, "extension_campaign_add")
            return {"ok": True, "count": len(cfg["members"])}

        raise HTTPException(422, "Unknown action")
