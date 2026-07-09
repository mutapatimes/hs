"""Product-catalog PDF builder (Shopify-first).

Fetch the store's products (a new, product-centric pull — not customer data, so it may be RAM-cached
freely), let the merchant pick a set / collections / tags, and generate a shareable print-ready PDF.
The PDF is stored in the DB (base64) and served at a public, unguessable URL that can be dropped into
a client email via the {catalog_link} token.
"""
from __future__ import annotations

import json
import math
import secrets
import time
from typing import Any

from fastapi import Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from halia import config
from halia.api.shopify_auth import require_shop, shop_store

_PRODUCT_CACHE: dict = {}     # shop -> {"at": monotonic, "products": [...]}
_TTL = 600.0                  # 10 min — products change rarely; keep the picker snappy
PAGE_SIZE = 24

_FIELD_KEYS = ("image", "title", "vendor", "price", "description", "sku", "variants")
_DEFAULT_FIELDS = {"image": True, "title": True, "vendor": True, "price": True,
                   "description": False, "sku": False, "variants": False}


def _clamp_int(v, default: int, lo: int, hi: int) -> int:
    try:
        return min(hi, max(lo, int(v)))
    except (TypeError, ValueError):
        return default


def _clean_fields(raw) -> dict:
    out = dict(_DEFAULT_FIELDS)
    if isinstance(raw, dict):
        for k in _FIELD_KEYS:
            if k in raw:
                out[k] = bool(raw[k])
    return out


import re as _re

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(v) -> str:
    s = str(v or "").strip()
    return s if _EMAIL_RE.match(s) else ""


def _default_enquiry_email(shop: str) -> str:
    """Fall back to the tenant's alert recipient when a catalogue has no explicit enquiry email."""
    try:
        from halia.api.settings import settings_for
        return (settings_for(shop) or {}).get("notify_email") or ""
    except Exception:  # noqa: BLE001 — never let a settings hiccup break enquiry delivery
        return ""


# Lightweight anti-mailbomb throttle: at most N enquiries per catalogue per minute (RAM only).
_ENQ_HITS: dict = {}


def _enquiry_allowed(catalog_id: str, now: float, cap: int = 12) -> bool:
    bucket = int(now // 60)
    key = (catalog_id, bucket)
    _ENQ_HITS.clear() if len(_ENQ_HITS) > 2000 else None
    n = _ENQ_HITS.get(key, 0)
    if n >= cap:
        return False
    _ENQ_HITS[key] = n + 1
    return True


def _price_str(pr: dict) -> str:
    sym = {"GBP": "£", "EUR": "€", "USD": "$", "JPY": "¥"}.get(pr.get("currency") or "")
    amt = pr.get("price")
    if amt in (None, ""):
        return ""
    try:
        return f"{sym}{float(amt):,.2f}" if sym else f"{float(amt):,.2f} {pr.get('currency') or ''}".strip()
    except (TypeError, ValueError):
        return ""


def _enquiry_html(cat_name, name, email, phone, message, picked) -> str:
    import html as _h
    rows = "".join(
        f'<tr><td style="padding:6px 10px;border-bottom:1px solid #eee">{_h.escape(pr.get("title") or "")}'
        + (f' <span style="color:#9a9385">· {_h.escape(pr["sku"])}</span>' if pr.get("sku") else "")
        + f'</td><td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#1f564a">'
        f'{_h.escape(_price_str(pr))}</td></tr>'
        for pr in picked) or '<tr><td style="padding:6px 10px;color:#9a9385">(No specific products ticked)</td></tr>'
    msg = (f'<p style="margin:14px 0 0"><b>Message</b><br>{_h.escape(message)}</p>' if message else "")
    ph = (f' · {_h.escape(phone)}' if phone else "")
    return (f'<div style="font-family:Helvetica,Arial,sans-serif;color:#1a1712;max-width:560px">'
            f'<p style="font-size:15px">New enquiry from <b>{_h.escape(name)}</b> via your '
            f'<b>{_h.escape(cat_name)}</b> catalogue.</p>'
            f'<p style="margin:4px 0 16px;color:#555">{_h.escape(email)}{ph}</p>'
            f'<table style="border-collapse:collapse;width:100%;font-size:14px">'
            f'<thead><tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #1a1712">Product</th>'
            f'<th style="text-align:right;padding:6px 10px;border-bottom:2px solid #1a1712">Price</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>{msg}'
            f'<p style="margin-top:20px;color:#9a9385;font-size:12px">Sent to you by Halia. '
            f'Reply directly to {_h.escape(email)} to respond.</p></div>')


def _enquiry_text(cat_name, name, email, phone, message, picked) -> str:
    lines = [f"New enquiry from {name} via your {cat_name} catalogue.",
             f"{email}" + (f" · {phone}" if phone else ""), ""]
    for pr in picked:
        bit = f"- {pr.get('title') or ''}"
        if pr.get("sku"):
            bit += f" ({pr['sku']})"
        if _price_str(pr):
            bit += f" — {_price_str(pr)}"
        lines.append(bit)
    if not picked:
        lines.append("(No specific products ticked)")
    if message:
        lines += ["", f"Message: {message}"]
    lines += ["", f"Reply directly to {email} to respond."]
    return "\n".join(lines)


def _products(shop: str, force: bool = False) -> list[dict]:
    ent = _PRODUCT_CACHE.get(shop)
    if not force and ent and (time.monotonic() - ent["at"] < _TTL):
        return ent["products"]
    token = shop_store().get_token(shop)
    if not token:                                 # Shopify-only for now
        raise HTTPException(400, "Catalogs are available for Shopify stores for now.")
    from scoring.shopify_fetch import fetch_products, http_transport
    prods = fetch_products(http_transport(shop, token),
                           max_pages=config.SHOPIFY_PRODUCTS_MAX_PAGES)
    prods = [p for p in prods if p.get("status") in (None, "ACTIVE")]   # skip drafts/archived
    _PRODUCT_CACHE[shop] = {"at": time.monotonic(), "products": prods}
    return prods


def _facets(prods: list[dict]) -> dict:
    cols, tags, vendors = set(), set(), set()
    for p in prods:
        cols.update(p.get("collections") or [])
        tags.update(p.get("tags") or [])
        if p.get("vendor"):
            vendors.add(p["vendor"])
    return {"collections": sorted(cols)[:200], "tags": sorted(tags)[:200],
            "vendors": sorted(vendors)[:200]}


def _resolve(shop: str, selection: dict) -> list[dict]:
    """Products for a catalog from its saved selection (explicit ids OR collection/tag/vendor)."""
    prods = _products(shop)
    ids = set(selection.get("product_ids") or [])
    cols = set(selection.get("collections") or [])
    tags = set(selection.get("tags") or [])
    vendors = set(selection.get("vendors") or [])
    out = []
    for p in prods:
        if (p["id"] in ids
                or (cols and set(p.get("collections") or []) & cols)
                or (tags and set(p.get("tags") or []) & tags)
                or (vendors and p.get("vendor") in vendors)):
            out.append(p)
    return out


def _shop_display(shop: str) -> str:
    t = shop_store().get_tenant(shop)
    return (t or {}).get("label") or str(shop).replace(".myshopify.com", "")


def catalog_url_for(shop: str) -> str:
    """The active catalog's public URL for {catalog_link}, or '' if none is set/generated."""
    cat = shop_store().active_catalog(shop)
    if not cat:
        return ""
    base = (config.HALIA_APP_URL or "").rstrip("/")
    return f"{base}/catalog/{cat['id']}.pdf" if base else f"/catalog/{cat['id']}.pdf"


def register(app) -> None:

    @app.get("/v1/catalog/products")
    def catalog_products(request: Request, shop: str = Depends(require_shop)) -> dict:
        qp = request.query_params
        prods = _products(shop, force=qp.get("refresh") == "1")
        search = (qp.get("search") or "").lower().strip()
        col, tag, vendor = qp.get("collection"), qp.get("tag"), qp.get("vendor")
        filt = [p for p in prods
                if (not search or search in p["title"].lower() or search in (p.get("vendor") or "").lower())
                and (not col or col in (p.get("collections") or []))
                and (not tag or tag in (p.get("tags") or []))
                and (not vendor or p.get("vendor") == vendor)]
        try:
            page = max(1, int(qp.get("page", "1") or 1))
        except ValueError:
            page = 1
        pages = max(1, math.ceil(len(filt) / PAGE_SIZE))
        page = min(page, pages)
        start = (page - 1) * PAGE_SIZE
        return {"items": filt[start:start + PAGE_SIZE], "total": len(filt),
                "all_total": len(prods), "page": page, "pages": pages,
                "ids": [p["id"] for p in filt],   # all filtered ids, for "select all"
                "facets": _facets(prods)}

    @app.get("/v1/catalog/list")
    def catalog_list(shop: str = Depends(require_shop)) -> dict:
        base = (config.HALIA_APP_URL or "").rstrip("/")
        out = []
        for c in shop_store().list_catalogs(shop):
            cfg = {}
            try:
                cfg = json.loads(c.get("config_json") or "{}")
            except (ValueError, TypeError):
                cfg = {}
            sel = cfg.get("selection", {}) or {}
            out.append({"id": c["id"], "name": c["name"], "active": bool(c["active"]),
                        "generated": bool(c.get("pdf_at")),
                        "url": (f"{base}/catalog/{c['id']}.pdf" if c.get("pdf_at") else ""),
                        "count": len(sel.get("product_ids") or []),
                        "template": cfg.get("template", "grid"),
                        "columns": cfg.get("columns", 3),
                        "page_size": cfg.get("page_size", "A4"),
                        "brand_color": cfg.get("brand_color", "#1f564a"),
                        "text_color": cfg.get("text_color", "#1a1712"),
                        "footer_text": cfg.get("footer_text", ""),
                        "cover": cfg.get("cover", True),
                        "enquiry_email": cfg.get("enquiry_email", ""),
                        "enquire": cfg.get("enquire", True),
                        "form_url": (f"{base}/catalog/{c['id']}" if base else f"/catalog/{c['id']}"),
                        "fields": _clean_fields(cfg.get("fields")),
                        "product_ids": sel.get("product_ids") or []})
        return {"catalogs": out}

    @app.post("/v1/catalog/save")
    def catalog_save(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        name = (str(p.get("name") or "").strip() or "Untitled catalogue")[:120]
        cid = str(p.get("id") or "").strip() or ("cat_" + secrets.token_urlsafe(9))
        if p.get("id"):                                   # editing: must own it
            existing = shop_store().get_catalog(cid)
            if existing and existing["shop"] != shop:
                raise HTTPException(403, "Not your catalogue.")
        cfg = {
            "template": p.get("template") if p.get("template") in ("grid", "list", "minimal", "lookbook") else "grid",
            "columns": _clamp_int(p.get("columns"), 3, 1, 4),
            "page_size": p.get("page_size") if p.get("page_size") in ("A4", "Letter") else "A4",
            "brand_color": (str(p.get("brand_color") or "#1f564a"))[:9],
            "text_color": (str(p.get("text_color") or "#1a1712"))[:9],
            "footer_text": (str(p.get("footer_text") or "").strip())[:160],
            "cover": bool(p.get("cover", True)),
            "enquiry_email": _clean_email(p.get("enquiry_email")),
            "enquire": bool(p.get("enquire", True)),
            "fields": _clean_fields(p.get("fields")),
            "selection": {
                "product_ids": [str(x) for x in (p.get("product_ids") or [])][:400],
                "collections": [str(x) for x in (p.get("collections") or [])][:50],
                "tags": [str(x) for x in (p.get("tags") or [])][:50],
                "vendors": [str(x) for x in (p.get("vendors") or [])][:50],
            },
        }
        shop_store().save_catalog(cid, shop, name, json.dumps(cfg), active=bool(p.get("active")))
        return {"id": cid}

    @app.post("/v1/catalog/{catalog_id}/active")
    def catalog_activate(catalog_id: str, shop: str = Depends(require_shop)) -> dict:
        cat = shop_store().get_catalog(catalog_id)
        if not cat or cat["shop"] != shop:
            raise HTTPException(404, "Catalogue not found.")
        shop_store().set_active_catalog(catalog_id, shop)
        return {"ok": True, "catalog_url": catalog_url_for(shop)}

    @app.delete("/v1/catalog/{catalog_id}")
    def catalog_delete(catalog_id: str, shop: str = Depends(require_shop)) -> dict:
        shop_store().delete_catalog(catalog_id, shop)
        return {"ok": True}

    @app.post("/v1/catalog/{catalog_id}/generate")
    def catalog_generate(catalog_id: str, shop: str = Depends(require_shop)) -> dict:
        from halia.catalog_render import PdfEngineUnavailable, catalog_html, html_to_pdf
        cat = shop_store().get_catalog(catalog_id)
        if not cat or cat["shop"] != shop:
            raise HTTPException(404, "Catalogue not found.")
        cfg = json.loads(cat.get("config_json") or "{}")
        products = _resolve(shop, cfg.get("selection") or {})
        if not products:
            raise HTTPException(400, "Select at least one product before generating.")
        spec = dict(cfg)                       # template, columns, page_size, colours, cover, fields
        spec["name"] = cat["name"]
        html = catalog_html(spec, products, _shop_display(shop))
        try:
            pdf = html_to_pdf(html)
        except PdfEngineUnavailable as exc:
            raise HTTPException(503, "The PDF engine is not available in this environment yet.") from exc
        shop_store().set_catalog_pdf(catalog_id, pdf)
        base = (config.HALIA_APP_URL or "").rstrip("/")
        return {"url": (f"{base}/catalog/{catalog_id}.pdf" if base else f"/catalog/{catalog_id}.pdf"),
                "count": len(products)}

    @app.get("/catalog/{catalog_id}.pdf")
    def catalog_pdf(catalog_id: str):
        pdf = shop_store().get_catalog_pdf(catalog_id)     # public: recipients open the link
        if not pdf:
            raise HTTPException(404, "Not found")
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="catalogue.pdf"',
                                 "Cache-Control": "public, max-age=3600"})

    @app.get("/catalog/{catalog_id}")
    def catalog_form_page(catalog_id: str, request: Request):
        """Public, interactive version of the catalogue: tick products, submit an enquiry.
        ?name=&email=&phone= prefill the form so a personalised link is one tap to send."""
        from fastapi.responses import HTMLResponse
        from halia.catalog_form import catalog_form_html
        cat = shop_store().get_catalog(catalog_id)
        if not cat:
            raise HTTPException(404, "Catalogue not found.")
        cfg = json.loads(cat.get("config_json") or "{}")
        shop = cat["shop"]
        products = _resolve(shop, cfg.get("selection") or {})
        prefill = {k: (request.query_params.get(k) or "")[:160] for k in ("name", "email", "phone")}
        html = catalog_form_html(
            {"name": cat["name"], "brand_color": cfg.get("brand_color"), "fields": cfg.get("fields")},
            products, shop_name=_shop_display(shop), catalog_id=catalog_id,
            enquiry_email=cfg.get("enquiry_email") or _default_enquiry_email(shop), prefill=prefill)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.post("/catalog/{catalog_id}/enquire")
    def catalog_enquire(catalog_id: str, payload: Any = Body(...)) -> dict:
        """A recipient's enquiry: email the ticked products + their details to the merchant.
        Zero-retention — nothing about the enquirer is stored."""
        cat = shop_store().get_catalog(catalog_id)
        if not cat:
            raise HTTPException(404, "Catalogue not found.")
        p = payload or {}
        if str(p.get("company") or "").strip():        # honeypot — silently accept & drop bots
            return {"ok": True}
        name = str(p.get("name") or "").strip()[:120]
        email = _clean_email(p.get("email"))
        if not name or not email:
            raise HTTPException(400, "Please add your name and a valid email.")
        if not _enquiry_allowed(catalog_id, time.monotonic()):
            raise HTTPException(429, "Too many enquiries just now. Please try again in a minute.")
        phone = str(p.get("phone") or "").strip()[:60]
        message = str(p.get("message") or "").strip()[:2000]
        ids = {str(x) for x in (p.get("product_ids") or [])[:400]}
        cfg = json.loads(cat.get("config_json") or "{}")
        shop = cat["shop"]
        picked = [pr for pr in _resolve(shop, cfg.get("selection") or {}) if pr["id"] in ids]
        to = cfg.get("enquiry_email") or _default_enquiry_email(shop)
        if not to:
            raise HTTPException(400, "This catalogue has no enquiry address set.")
        from halia.notify import send_email
        subject = f"New catalogue enquiry from {name}"
        ok = send_email(to, subject,
                        _enquiry_html(cat["name"], name, email, phone, message, picked),
                        _enquiry_text(cat["name"], name, email, phone, message, picked), shop=shop)
        if not ok:
            raise HTTPException(502, "Could not send the enquiry just now. Please try again.")
        return {"ok": True}
