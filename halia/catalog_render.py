"""Render a product catalog to HTML and (via WeasyPrint) to a print-ready PDF.

HTML is hand-built with f-strings (the repo style — see halia/api/blog.py), so there is no Jinja2
dependency. WeasyPrint is imported LAZILY inside ``html_to_pdf`` because it needs system libraries
(cairo/pango) that are present in the Docker image but not in local dev / CI; when it can't be
imported the caller gets ``PdfEngineUnavailable`` and the app keeps running (the endpoint 503s).
WeasyPrint fetches the product images from their URLs itself at render time.
"""
from __future__ import annotations

import html as _html

_CUR_SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$", "JPY": "¥", "AUD": "$", "CAD": "$"}


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


def _card(p: dict) -> str:
    img = p.get("image_url")
    media = (f'<div class="ph"><img src="{_esc(img)}" alt=""></div>' if img
             else '<div class="ph noimg"></div>')
    vendor = f'<div class="vendor">{_esc(p["vendor"])}</div>' if p.get("vendor") else ""
    price = f'<div class="price">{_esc(_price(p))}</div>' if _price(p) else ""
    return (f'<div class="card">{media}'
            f'<div class="meta">{vendor}<div class="title">{_esc(p.get("title"))}</div>'
            f'{price}</div></div>')


def catalog_html(catalog: dict, products: list[dict], shop_name: str = "") -> str:
    """A full, print-ready HTML document for the catalog (cover page + product grid)."""
    name = catalog.get("name") or "Product Catalogue"
    brand = catalog.get("brand_color") or "#1f564a"
    template = catalog.get("template") or "grid"
    cols = 2 if template == "lookbook" else 3
    cards = "".join(_card(p) for p in products) or '<div class="empty">No products selected.</div>'
    n = len(products)
    subtitle = _esc(shop_name) if shop_name else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<style>
  @page {{ size: A4; margin: 16mm 14mm 18mm;
    @bottom-center {{ content: "{_esc(name)}"; font: 8pt 'Helvetica'; color: #9a9385; }}
    @bottom-right {{ content: counter(page); font: 8pt 'Helvetica'; color: #9a9385; }} }}
  @page :first {{ margin: 0; @bottom-center {{ content: none; }} @bottom-right {{ content: none; }} }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: 'Helvetica', Arial, sans-serif; color: #1a1712; }}
  .cover {{ page-break-after: always; height: 297mm; padding: 40mm 28mm; position: relative;
    display: flex; flex-direction: column; justify-content: flex-end; }}
  .cover::before {{ content: ""; position: absolute; inset: 0 0 auto; height: 46mm; background: {brand}; }}
  .cover .eyebrow {{ font: 600 10pt 'Helvetica'; letter-spacing: .28em; text-transform: uppercase;
    color: {brand}; margin-bottom: 10mm; }}
  .cover h1 {{ font: 300 40pt Georgia, serif; margin: 0 0 6mm; line-height: 1.02; max-width: 20ch; }}
  .cover .sub {{ font: 400 13pt 'Helvetica'; color: #615b50; }}
  .cover .count {{ margin-top: 14mm; font: 600 9pt 'Helvetica'; letter-spacing: .1em;
    text-transform: uppercase; color: #9a9385; }}
  .grid {{ display: grid; grid-template-columns: repeat({cols}, 1fr); gap: 10mm 8mm; padding-top: 2mm; }}
  .card {{ page-break-inside: avoid; }}
  .ph {{ width: 100%; aspect-ratio: 4/5; background: #f2f0ea; border-radius: 3mm; overflow: hidden; }}
  .ph img {{ width: 100%; height: 100%; object-fit: cover; }}
  .ph.noimg {{ background: #efeadd; }}
  .meta {{ padding-top: 3mm; }}
  .vendor {{ font: 600 7.5pt 'Helvetica'; letter-spacing: .1em; text-transform: uppercase; color: #9a9385; }}
  .title {{ font: 400 12pt Georgia, serif; margin: 1.5mm 0; line-height: 1.2; }}
  .price {{ font: 600 10pt 'Helvetica'; color: {brand}; }}
  .empty {{ color: #9a9385; padding: 20mm; text-align: center; }}
</style></head><body>
  <section class="cover">
    <div class="eyebrow">{subtitle or "Catalogue"}</div>
    <h1>{_esc(name)}</h1>
    {f'<div class="sub">{subtitle}</div>' if subtitle else ''}
    <div class="count">{n} product{'s' if n != 1 else ''}</div>
  </section>
  <div class="grid">{cards}</div>
</body></html>"""


def html_to_pdf(html: str) -> bytes:
    """Rasterise HTML to PDF bytes via WeasyPrint. Raises PdfEngineUnavailable if unimportable."""
    try:
        from weasyprint import HTML  # lazy: needs cairo/pango (present in the Docker image)
    except Exception as exc:  # noqa: BLE001 — ImportError or an OSError from missing native libs
        raise PdfEngineUnavailable(str(exc)) from exc
    return HTML(string=html).write_pdf()
