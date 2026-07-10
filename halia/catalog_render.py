"""Render a product catalog to HTML and (via WeasyPrint) to a print-ready PDF.

HTML is hand-built with f-strings (the repo style — see halia/api/blog.py), so there is no Jinja2
dependency. WeasyPrint is imported LAZILY inside ``html_to_pdf`` because it needs system libraries
(cairo/pango) that are present in the Docker image but not in local dev / CI; when it can't be
imported the caller gets ``PdfEngineUnavailable`` and the app keeps running (the endpoint 503s).
WeasyPrint fetches the product images from their URLs itself at render time.

The catalog dict understands these keys (all optional, with sensible defaults so older saved
catalogs keep rendering unchanged):
  name, brand_color, text_color, footer_text,
  template   -> "grid" | "list" | "minimal" (legacy "lookbook" == 2-column grid),
  columns    -> 1..4 (grid / minimal only),
  page_size  -> "A4" | "Letter",
  cover      -> bool (default True),
  fields     -> {image,title,vendor,price,description,sku,variants: bool}
"""
from __future__ import annotations

import html as _html
import re as _re
from urllib.parse import quote as _q

_CUR_SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$", "JPY": "¥", "AUD": "$", "CAD": "$"}

_DEFAULT_FIELDS = {"image": True, "title": True, "vendor": True, "price": True,
                   "description": False, "sku": False, "variants": False}

_PAGE = {
    "A4":     {"size": "A4",     "cover_h": "297mm", "margin": "16mm 14mm 18mm"},
    "Letter": {"size": "Letter", "cover_h": "11in",  "margin": "0.7in 0.6in 0.7in"},
}


class PdfEngineUnavailable(RuntimeError):
    """WeasyPrint (or its system libraries) is not available in this environment."""


def _esc(s: object) -> str:
    return _html.escape(str(s if s is not None else ""))


def _price(p: dict) -> str:
    amt, cur = p.get("price"), p.get("currency") or ""
    if amt in (None, ""):
        return ""
    try:
        v = float(amt)
    except (TypeError, ValueError):
        return ""
    sym = _CUR_SYMBOL.get(cur)
    return f"{sym}{v:,.2f}" if sym else (f"{v:,.2f} {cur}".strip())


def _desc(p: dict, limit: int = 200) -> str:
    raw = _re.sub(r"\s+", " ", str(p.get("description") or "")).strip()
    if len(raw) > limit:
        raw = raw[:limit].rsplit(" ", 1)[0].rstrip(",.;: ") + "…"
    return raw


def _mailto(email: str, p: dict, cat_name: str) -> str:
    title = str(p.get("title") or "")
    subject = f"Enquiry: {title}" if title else "Product enquiry"
    body = f"Hello,\n\nI would like to enquire about {title}"
    if p.get("sku"):
        body += f" (SKU {p['sku']})"
    body += f".\n\n(From {cat_name})\n"
    return f"mailto:{_q(email)}?subject={_q(subject)}&body={_q(body)}"


def _card(p: dict, fields: dict, enquiry_email: str = "", cat_name: str = "") -> str:
    parts = []
    if fields.get("image"):
        img = p.get("image_url")
        parts.append(f'<div class="ph"><img src="{_esc(img)}" alt=""></div>' if img
                     else '<div class="ph noimg"></div>')
    meta = []
    if fields.get("vendor") and p.get("vendor"):
        meta.append(f'<div class="vendor">{_esc(p["vendor"])}</div>')
    if fields.get("title"):
        meta.append(f'<div class="title">{_esc(p.get("title"))}</div>')
    if fields.get("sku") and p.get("sku"):
        meta.append(f'<div class="sku">{_esc(p["sku"])}</div>')
    row = []
    if fields.get("price") and _price(p):
        row.append(f'<span class="price">{_esc(_price(p))}</span>')
    if fields.get("variants") and p.get("variants"):
        n = p["variants"]
        row.append(f'<span class="variants">{n} variant{"s" if n != 1 else ""}</span>')
    if row:
        meta.append(f'<div class="priceline">{"".join(row)}</div>')
    if fields.get("description") and _desc(p):
        meta.append(f'<div class="desc">{_esc(_desc(p))}</div>')
    if enquiry_email:
        meta.append(f'<a class="enquire" href="{_esc(_mailto(enquiry_email, p, cat_name))}">Enquire</a>')
    parts.append(f'<div class="meta">{"".join(meta)}</div>')
    return f'<div class="card">{"".join(parts)}</div>'


def _norm(catalog: dict) -> dict:
    """Resolve a catalog dict to a fully-defaulted, validated render spec."""
    template = catalog.get("template") or "grid"
    if template == "lookbook":                       # legacy alias
        template, cols_default = "grid", 2
    else:
        cols_default = 3
    if template not in ("grid", "list", "minimal"):
        template = "grid"
    try:
        columns = int(catalog.get("columns") or cols_default)
    except (TypeError, ValueError):
        columns = cols_default
    columns = min(4, max(1, columns))
    fields = dict(_DEFAULT_FIELDS)
    for k, v in (catalog.get("fields") or {}).items():
        if k in fields:
            fields[k] = bool(v)
    return {
        "name": catalog.get("name") or "Product Catalogue",
        "subtitle": str(catalog.get("subtitle") or "").strip(),   # personal line, e.g. "Prepared for Jane"
        "logo": str(catalog.get("logo") or "").strip(),           # retailer logo (data: URI or URL)
        "brand": catalog.get("brand_color") or "#1f564a",
        "text": catalog.get("text_color") or "#1a1712",
        "template": template,
        "columns": columns,
        "page": _PAGE.get(catalog.get("page_size"), _PAGE["A4"]),
        "cover": bool(catalog.get("cover", True)),
        "footer": (str(catalog.get("footer_text") or "").strip()
                   or (catalog.get("name") or "Product Catalogue")),
        "fields": fields,
        "enquiry_email": str(catalog.get("enquiry_email") or "").strip(),
        "enquire": bool(catalog.get("enquire", True)),
    }


def catalog_html(catalog: dict, products: list[dict], shop_name: str = "") -> str:
    """A full, print-ready HTML document for the catalog (optional cover + product layout)."""
    s = _norm(catalog)
    brand, text, page = s["brand"], s["text"], s["page"]
    cols = 1 if s["template"] == "list" else s["columns"]
    enq = s["enquiry_email"] if s["enquire"] else ""
    cards = "".join(_card(p, s["fields"], enq, s["name"]) for p in products) \
        or '<div class="empty">No products selected.</div>'
    n = len(products)
    eyebrow = _esc(shop_name) if shop_name else "Catalogue"
    personal = _esc(s["subtitle"]) if s["subtitle"] else ""
    cover = ""
    if s["cover"]:
        logo = f'<img class="logo" src="{_esc(s["logo"])}" alt="">' if s["logo"] else ""
        cover = f"""<section class="cover">
    {logo}
    <div class="eyebrow">{eyebrow}</div>
    <h1>{_esc(s["name"])}</h1>
    {f'<div class="sub">{personal}</div>' if personal else ''}
    <div class="count">{n} product{'s' if n != 1 else ''}</div>
  </section>"""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<style>
  @page {{ size: {page['size']}; margin: {page['margin']};
    @bottom-center {{ content: "{_esc(s['footer'])}"; font: 8pt 'Helvetica'; color: #9a9385; }}
    @bottom-right {{ content: counter(page); font: 8pt 'Helvetica'; color: #9a9385; }} }}
  {'@page :first { margin: 0; @bottom-center { content: none; } @bottom-right { content: none; } }' if s['cover'] else ''}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: 'Helvetica', Arial, sans-serif; color: {text}; }}
  .cover {{ page-break-after: always; height: {page['cover_h']}; padding: 40mm 28mm; position: relative;
    display: flex; flex-direction: column; justify-content: flex-end; }}
  .cover::before {{ content: ""; position: absolute; inset: 0 0 auto; height: 2.5mm; background: {brand}; }}
  .cover .logo {{ position: absolute; top: 16mm; left: 28mm; max-height: 16mm; max-width: 62mm;
    object-fit: contain; z-index: 2; }}
  .cover .eyebrow {{ font: 600 9pt 'Helvetica'; letter-spacing: .22em; text-transform: uppercase;
    color: #8a857a; margin-bottom: 9mm; }}
  .cover h1 {{ font: 400 32pt 'Helvetica', Arial, sans-serif; margin: 0 0 6mm; line-height: 1.05;
    letter-spacing: -.2pt; max-width: 22ch; color: {text}; }}
  .cover .sub {{ font: 400 12pt 'Helvetica'; color: #615b50; }}
  .cover .count {{ margin-top: 13mm; font: 600 8.5pt 'Helvetica'; letter-spacing: .1em;
    text-transform: uppercase; color: #9a9385; }}
  .items {{ display: grid; grid-template-columns: repeat({cols}, 1fr); gap: 10mm 8mm; padding-top: 2mm; }}
  .card {{ page-break-inside: avoid; }}
  .ph {{ width: 100%; aspect-ratio: 4/5; background: #f4f4f2; overflow: hidden; }}
  .ph img {{ width: 100%; height: 100%; object-fit: cover; }}
  .ph.noimg {{ background: #f0f0ee; }}
  .meta {{ padding-top: 3mm; }}
  .vendor {{ font: 600 7pt 'Helvetica'; letter-spacing: .1em; text-transform: uppercase; color: #9a9385; }}
  .title {{ font: 500 11pt 'Helvetica', Arial, sans-serif; margin: 1.5mm 0; line-height: 1.25; color: {text}; }}
  .sku {{ font: 500 7.5pt 'Helvetica'; letter-spacing: .04em; color: #9a9385; margin-bottom: 1mm; }}
  .priceline {{ display: flex; align-items: baseline; gap: 3mm; }}
  .price {{ font: 600 10pt 'Helvetica'; color: {text}; }}
  .variants {{ font: 500 8pt 'Helvetica'; color: #9a9385; }}
  .desc {{ font: 400 8.5pt 'Helvetica'; line-height: 1.45; color: #615b50; margin-top: 2mm; }}
  .enquire {{ display: inline-block; margin-top: 2.5mm; font: 600 8pt 'Helvetica'; color: {text};
    text-decoration: none; border: 0.3mm solid #c7c3b9; border-radius: 1mm; padding: 1mm 3.5mm; }}
  /* list — a detailed row per product */
  .items.list {{ display: block; }}
  .items.list .card {{ display: flex; gap: 6mm; align-items: flex-start;
    padding: 5mm 0; border-bottom: 0.3mm solid #e7e3da; }}
  .items.list .ph {{ width: 34mm; flex: none; aspect-ratio: 1/1; }}
  .items.list .meta {{ padding-top: 0; flex: 1; }}
  .items.list .desc {{ max-width: 120mm; }}
  /* minimal — image-forward, centred, quiet text */
  .items.minimal .ph {{ aspect-ratio: 1/1; }}
  .items.minimal .meta {{ text-align: center; }}
  .items.minimal .priceline {{ justify-content: center; }}
  .empty {{ color: #9a9385; padding: 20mm; text-align: center; }}
</style></head><body>
  {cover}
  <div class="items {s['template']}">{cards}</div>
</body></html>"""


def html_to_pdf(html: str) -> bytes:
    """Rasterise HTML to PDF bytes via WeasyPrint. Raises PdfEngineUnavailable if unimportable."""
    try:
        from weasyprint import HTML  # lazy: needs cairo/pango (present in the Docker image)
    except Exception as exc:  # noqa: BLE001 — ImportError or an OSError from missing native libs
        raise PdfEngineUnavailable(str(exc)) from exc
    return HTML(string=html).write_pdf()
