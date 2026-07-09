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
