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
from halia.api.shopify_auth import require_shop, shop_store, verify_app_proxy

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


def _clean_logo(v) -> str:
    """Accept a retailer logo as a data: URI (uploaded) or an http(s) URL; cap the size."""
    s = str(v or "").strip()
    if s.startswith("data:image/") or s.startswith("http://") or s.startswith("https://"):
        return s[:400_000]
    return ""


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


def _fetch_products_for(shop: str) -> list[dict]:
    """Pull catalogue products from whichever platform this tenant is on (Shopify or WooCommerce)."""
    kind = (shop_store().get_tenant(shop) or {}).get("kind")
    if kind == "woocommerce":
        creds = shop_store().get_woocommerce(shop)
        if not creds:
            raise HTTPException(400, "Connect your WooCommerce store first.")
        from scoring.woocommerce_fetch import fetch_products, http_transport
        return fetch_products(http_transport(creds["store_url"], creds["consumer_key"],
                                             creds["consumer_secret"]), max_pages=config.WOO_MAX_PAGES)
    token = shop_store().get_token(shop)
    if token:                                     # Shopify
        from scoring.shopify_fetch import fetch_products, http_transport
        return fetch_products(http_transport(shop, token), max_pages=config.SHOPIFY_PRODUCTS_MAX_PAGES)
    raise HTTPException(400, "Catalogues aren't available for this store type yet.")


def _products(shop: str, force: bool = False) -> list[dict]:
    ent = _PRODUCT_CACHE.get(shop)
    if not force and ent and (time.monotonic() - ent["at"] < _TTL):
        return ent["products"]
    prods = [p for p in _fetch_products_for(shop) if p.get("status") in (None, "ACTIVE")]  # skip drafts
    _PRODUCT_CACHE[shop] = {"at": time.monotonic(), "products": prods}
    return prods


def _facets(prods: list[dict]) -> dict:
    cols, tags, vendors, sizes = set(), set(), set(), set()
    for p in prods:
        cols.update(p.get("collections") or [])
        tags.update(p.get("tags") or [])
        sizes.update(p.get("sizes") or [])
        if p.get("vendor"):
            vendors.add(p["vendor"])
    return {"collections": sorted(cols)[:200], "tags": sorted(tags)[:200],
            "vendors": sorted(vendors)[:200], "sizes": _sort_sizes(sizes)[:200]}


# Common apparel/shoe sizes in wearing order, so the filter reads S, M, L (not L, M, S).
_SIZE_ORDER = ["xxxs", "xxs", "xs", "s", "small", "m", "medium", "l", "large",
               "xl", "xxl", "2xl", "xxxl", "3xl", "4xl", "5xl", "one size", "os"]


def _sort_sizes(sizes) -> list[str]:
    def key(s: str):
        low = s.strip().lower()
        if low in _SIZE_ORDER:
            return (0, _SIZE_ORDER.index(low), "")
        try:                                        # numeric sizes (shoe / waist) sort numerically
            return (1, float(low.replace(",", ".")), "")
        except ValueError:
            return (2, 0, low)
    return sorted(sizes, key=key)


def _resolve(shop: str, selection: dict) -> list[dict]:
    """Products for a catalog from its saved selection. Explicit ids come first, IN THE SAVED ORDER
    (so the merchant's manual ordering is honoured), then any collection/tag/vendor matches."""
    prods = _products(shop)
    by_id = {p["id"]: p for p in prods}
    id_list = [str(x) for x in (selection.get("product_ids") or [])]
    cols = set(selection.get("collections") or [])
    tags = set(selection.get("tags") or [])
    vendors = set(selection.get("vendors") or [])
    out, seen = [], set()
    for pid in id_list:                              # explicit picks, in the merchant's order
        p = by_id.get(pid)
        if p and pid not in seen:
            out.append(p)
            seen.add(pid)
    if cols or tags or vendors:                      # then facet matches (product order)
        for p in prods:
            if p["id"] in seen:
                continue
            if ((cols and set(p.get("collections") or []) & cols)
                    or (tags and set(p.get("tags") or []) & tags)
                    or (vendors and p.get("vendor") in vendors)):
                out.append(p)
                seen.add(p["id"])
    return out


def _shop_display(shop: str) -> str:
    t = shop_store().get_tenant(shop)
    return (t or {}).get("label") or str(shop).replace(".myshopify.com", "")


_DOMAIN_CACHE: dict = {}     # shop -> {"at": monotonic, "host": "theirbrand.com"}


def _primary_domain(shop: str) -> str:
    """The store's primary STOREFRONT domain (e.g. theirbrand.com), for white-label catalogue
    links via the Shopify App Proxy. Cached; best-effort (empty string if unavailable)."""
    ent = _DOMAIN_CACHE.get(shop)
    if ent and (time.monotonic() - ent["at"] < 3600):
        return ent["host"]
    host = ""
    token = shop_store().get_token(shop)
    if token:
        try:
            from scoring.shopify_fetch import _run, http_transport
            data = _run(http_transport(shop, token), "{ shop { primaryDomain { host } } }", {}, 2)
            host = ((data.get("shop") or {}).get("primaryDomain") or {}).get("host") or ""
        except Exception:  # noqa: BLE001 — never let a link lookup break the request
            host = ""
    _DOMAIN_CACHE[shop] = {"at": time.monotonic(), "host": host}
    return host


def _tenant_catalog_domain(shop: str) -> str:
    """A merchant's own catalogue host (CNAME'd to Halia), set in Settings — used to white-label
    links for WooCommerce (and any non-Shopify) stores where the App Proxy isn't available."""
    try:
        from halia.api.settings import settings_for
        return (settings_for(shop) or {}).get("catalog_domain") or ""
    except Exception:  # noqa: BLE001
        return ""


def catalog_share_base(shop: str) -> str:
    """Base URL for a shareable catalogue link, white-label first so a client never sees a Halia URL:
    the Shopify App Proxy on the store's own domain, else the merchant's own CNAME'd catalogue
    domain, else (last resort) the Halia app URL."""
    host = _primary_domain(shop)                       # Shopify: their storefront via the App Proxy
    if host:
        return f"https://{host}/{config.PROXY_PREFIX}/{config.PROXY_SUBPATH}"
    dom = _tenant_catalog_domain(shop)                 # any platform: their own CNAME'd host
    if dom:
        return f"https://{dom}/catalog"
    base = (config.HALIA_APP_URL or "").rstrip("/")
    return f"{base}/catalog" if base else "/catalog"


def catalog_url_for(shop: str) -> str:
    """The active catalogue's shareable (interactive form) URL for {catalog_link}, or '' if none set.
    The form renders live, so this works before a PDF is generated."""
    cat = shop_store().active_catalog(shop)
    if not cat:
        return ""
    return f"{catalog_share_base(shop)}/{cat['id']}"


# ── personalisation: the catalogue title + subtitle can carry {name}/{first_name}/{store} tokens,
#    filled from the recipient on a personalised share link (…?name=Jane) ───────────────────────
def _decode_name(token: str) -> str:
    """Decode an opaque personalisation token (base64url of the name) back to the name. The link
    carries ?c=<token> instead of ?name=Jane so a client doesn't see their own name in the URL —
    still zero-retention (the name lives only in the link, never stored)."""
    if not token:
        return ""
    import base64
    try:
        return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")[:160]
    except Exception:  # noqa: BLE001
        return ""


def _link_name(request: Request) -> str:
    """The recipient name from a share link: the opaque ?c token (preferred), else legacy ?name."""
    return (_decode_name(request.query_params.get("c") or "")
            or (request.query_params.get("name") or ""))[:160]


def _person_ctx(name: str, store: str) -> dict:
    name = (name or "").strip()
    first = (name.split() or [""])[0]
    return {"name": name or "you", "first_name": first or "you", "store": store or ""}


def _personalize(text: str, ctx: dict) -> str:
    text = str(text or "")
    for k, v in ctx.items():
        text = text.replace("{" + k + "}", v)
    return text


def _render_pdf(cat: dict, cfg: dict, shop: str, ctx: dict):
    """Render (name/subtitle personalised via ``ctx``) -> pdf bytes + product count."""
    from halia.catalog_render import catalog_html, html_to_pdf
    products = _resolve(shop, cfg.get("selection") or {})
    if not products:
        raise HTTPException(400, "Select at least one product before generating.")
    spec = dict(cfg)
    spec["name"] = _personalize(cat["name"], ctx)
    spec["subtitle"] = _personalize(cfg.get("subtitle", ""), ctx)
    return html_to_pdf(catalog_html(spec, products, _shop_display(shop))), len(products)


# ── shared serving (used by both the direct /catalog/… routes and the /proxy/catalogue/… routes
#    that Shopify's App Proxy hits so the page shows on the merchant's own domain) ────────────────
def _pdf_response(catalog_id: str, request: Request):
    from halia.catalog_render import PdfEngineUnavailable
    cat = shop_store().get_catalog(catalog_id)
    if not cat:
        raise HTTPException(404, "Not found")
    qname = _link_name(request).strip()
    pdf = None
    if qname:   # a personalised link -> render a fresh cover for this recipient
        try:
            cfg = json.loads(cat.get("config_json") or "{}")
            pdf, _ = _render_pdf(cat, cfg, cat["shop"], _person_ctx(qname, _shop_display(cat["shop"])))
        except (PdfEngineUnavailable, HTTPException, ValueError):
            pdf = None   # fall back to the stored generic PDF
    if pdf is None:
        pdf = shop_store().get_catalog_pdf(catalog_id)   # public: recipients open the link
    if not pdf:
        raise HTTPException(404, "Not found")
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="catalogue.pdf"',
                             "Cache-Control": "no-store" if qname else "public, max-age=3600"})


def _form_response(catalog_id: str, request: Request):
    from fastapi.responses import HTMLResponse
    from halia.catalog_form import catalog_form_html
    cat = shop_store().get_catalog(catalog_id)
    if not cat:
        raise HTTPException(404, "Catalogue not found.")
    cfg = json.loads(cat.get("config_json") or "{}")
    shop = cat["shop"]
    products = _resolve(shop, cfg.get("selection") or {})
    prefill = {"name": _link_name(request),
               "email": (request.query_params.get("email") or "")[:160],
               "phone": (request.query_params.get("phone") or "")[:160]}
    ctx = _person_ctx(prefill.get("name", ""), _shop_display(shop))
    html = catalog_form_html(
        {"name": _personalize(cat["name"], ctx), "subtitle": _personalize(cfg.get("subtitle", ""), ctx),
         "logo": cfg.get("logo", ""), "brand_color": cfg.get("brand_color"), "fields": cfg.get("fields")},
        products, shop_name=_shop_display(shop), catalog_id=catalog_id,
        enquiry_email=cfg.get("enquiry_email") or _default_enquiry_email(shop), prefill=prefill)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


def _do_enquire(catalog_id: str, payload) -> dict:
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
    ok = send_email(to, f"New catalogue enquiry from {name}",
                    _enquiry_html(cat["name"], name, email, phone, message, picked),
                    _enquiry_text(cat["name"], name, email, phone, message, picked),
                    shop=shop, reply_to=email)   # hit Reply -> straight to the shopper
    if not ok:
        raise HTTPException(502, "Could not send the enquiry just now. Please try again.")
    return {"ok": True}


def register(app) -> None:

    @app.get("/v1/catalog/products")
    def catalog_products(request: Request, shop: str = Depends(require_shop)) -> dict:
        from scoring.shopify_fetch import ShopifyAuthError
        qp = request.query_params
        try:
            prods = _products(shop, force=qp.get("refresh") == "1")
        except ShopifyAuthError as exc:
            # Almost always the read_products scope is missing (the original install predates the
            # catalogue feature). Tell the merchant to reconnect so the new scope is granted.
            raise HTTPException(403, "Halia needs product-read access. Reconnect your Shopify "
                                     "store (Settings → Integrations) to grant it.") from exc
        search = (qp.get("search") or "").lower().strip()
        col, tag, vendor = qp.get("collection"), qp.get("tag"), qp.get("vendor")
        size = (qp.get("size") or "").strip().lower()   # share only what fits the client
        filt = [p for p in prods
                if (not search or search in p["title"].lower() or search in (p.get("vendor") or "").lower())
                and (not col or col in (p.get("collections") or []))
                and (not tag or tag in (p.get("tags") or []))
                and (not vendor or p.get("vendor") == vendor)
                and (not size or size in [str(s).strip().lower() for s in (p.get("sizes") or [])])]
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
        base = catalog_share_base(shop)   # merchant's own domain (App Proxy) when available
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
                        "url": (f"{base}/{c['id']}.pdf" if c.get("pdf_at") else ""),
                        "count": len(sel.get("product_ids") or []),
                        "subtitle": cfg.get("subtitle", ""),
                        "logo": cfg.get("logo", ""),
                        "template": cfg.get("template", "grid"),
                        "columns": cfg.get("columns", 3),
                        "page_size": cfg.get("page_size", "A4"),
                        "brand_color": cfg.get("brand_color", "#1f564a"),
                        "text_color": cfg.get("text_color", "#1a1712"),
                        "footer_text": cfg.get("footer_text", ""),
                        "cover": cfg.get("cover", True),
                        "enquiry_email": cfg.get("enquiry_email", ""),
                        "enquire": cfg.get("enquire", True),
                        "form_url": f"{base}/{c['id']}",
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
            "subtitle": (str(p.get("subtitle") or "").strip())[:200],   # personal line (tokens allowed)
            "logo": _clean_logo(p.get("logo")),
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
        active = bool(p.get("active"))
        # Auto-activate the first catalogue so the per-client "Send catalogue" / "Copy catalogue
        # link" appear right away (they key off the active one).
        if not active and not shop_store().active_catalog(shop):
            active = True
        shop_store().save_catalog(cid, shop, name, json.dumps(cfg), active=active)
        return {"id": cid, "catalog_url": catalog_url_for(shop)}

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

    @app.post("/v1/catalog/preview")
    def catalog_preview(shop: str = Depends(require_shop), payload: Any = Body(...)):
        """Render the builder's CURRENT (unsaved) config to a PDF and stream it back, so a merchant
        can see the layout before committing. Nothing is stored."""
        from halia.catalog_render import PdfEngineUnavailable, catalog_html, html_to_pdf
        p = payload or {}
        selection = {
            "product_ids": [str(x) for x in (p.get("product_ids") or [])][:400],
            "collections": [str(x) for x in (p.get("collections") or [])][:50],
            "tags": [str(x) for x in (p.get("tags") or [])][:50],
            "vendors": [str(x) for x in (p.get("vendors") or [])][:50],
        }
        products = _resolve(shop, selection)
        if not products:
            raise HTTPException(400, "Select at least one product to preview.")
        ctx = _person_ctx(str(p.get("preview_name") or "").strip(), _shop_display(shop))
        spec = {
            "name": _personalize((str(p.get("name") or "").strip() or "Untitled catalogue")[:120], ctx),
            "subtitle": _personalize((str(p.get("subtitle") or "").strip())[:200], ctx),
            "logo": _clean_logo(p.get("logo")),
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
        }
        try:
            pdf = html_to_pdf(catalog_html(spec, products, _shop_display(shop)))
        except PdfEngineUnavailable as exc:
            raise HTTPException(503, "The PDF engine is not available in this environment yet.") from exc
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": 'inline; filename="preview.pdf"',
                                 "Cache-Control": "no-store"})

    @app.post("/v1/catalog/{catalog_id}/generate")
    def catalog_generate(catalog_id: str, shop: str = Depends(require_shop)) -> dict:
        from halia.catalog_render import PdfEngineUnavailable
        cat = shop_store().get_catalog(catalog_id)
        if not cat or cat["shop"] != shop:
            raise HTTPException(404, "Catalogue not found.")
        cfg = json.loads(cat.get("config_json") or "{}")
        try:   # generic version (tokens resolve to a neutral fallback); personalised copies render live
            pdf, count = _render_pdf(cat, cfg, shop, _person_ctx("", _shop_display(shop)))
        except PdfEngineUnavailable as exc:
            raise HTTPException(503, "The PDF engine is not available in this environment yet.") from exc
        shop_store().set_catalog_pdf(catalog_id, pdf)
        return {"url": f"{catalog_share_base(shop)}/{catalog_id}.pdf", "count": count}

    # ── Direct links (Halia domain) ──────────────────────────────────────────────────────────
    @app.get("/catalog/{catalog_id}.pdf")
    def catalog_pdf(catalog_id: str, request: Request):
        return _pdf_response(catalog_id, request)

    @app.get("/catalog/{catalog_id}")
    def catalog_form_page(catalog_id: str, request: Request):
        """Public, interactive version of the catalogue: tick products, submit an enquiry.
        ?name=&email=&phone= prefill the form so a personalised link is one tap to send."""
        return _form_response(catalog_id, request)

    @app.post("/catalog/{catalog_id}/enquire")
    def catalog_enquire(catalog_id: str, payload: Any = Body(...)) -> dict:
        return _do_enquire(catalog_id, payload)

    # ── App-Proxy links (merchant's OWN storefront domain: theirbrand.com/a/catalogue/…). Shopify
    #    forwards these here with a signed query string; we verify it before serving. Same content,
    #    but the client only ever sees the merchant's brand, never a Halia URL. ────────────────────
    @app.get("/proxy/catalogue/{catalog_id}.pdf")
    def proxy_pdf(catalog_id: str, request: Request):
        if not verify_app_proxy(request):
            raise HTTPException(403, "Invalid app-proxy signature.")
        return _pdf_response(catalog_id, request)

    @app.get("/proxy/catalogue/{catalog_id}")
    def proxy_form(catalog_id: str, request: Request):
        if not verify_app_proxy(request):
            raise HTTPException(403, "Invalid app-proxy signature.")
        return _form_response(catalog_id, request)

    @app.post("/proxy/catalogue/{catalog_id}/enquire")
    def proxy_enquire(catalog_id: str, request: Request, payload: Any = Body(...)) -> dict:
        if not verify_app_proxy(request):
            raise HTTPException(403, "Invalid app-proxy signature.")
        return _do_enquire(catalog_id, payload)
