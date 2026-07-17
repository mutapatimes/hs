"""Render a sample catalogue enquiry page through the real catalog_form_html path.

Proves the catalogue generator works end to end (the same renderer the live /catalog/<id>
route uses), on stand-in products with images from web/site/img so it opens standalone.
Writes web/site/catalogue-demo.html. Run: .venv/bin/python scripts/build_catalogue_demo.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from halia.catalog_form import catalog_form_html  # noqa: E402

OUT = ROOT / "web" / "site" / "catalogue-demo.html"

PRODUCTS = [
    {"id": "p1", "title": "Aurelle cashmere coat", "vendor": "Maison Aurelle", "type": "",
     "tags": ["new"], "collections": ["Outerwear"], "image_url": "img/luxurybag.jpg",
     "price": "1,450.00", "currency": "GBP", "status": "ACTIVE", "sizes": ["S", "M", "L"]},
    {"id": "p2", "title": "Estelle pearl necklace", "vendor": "Maison Aurelle", "type": "",
     "tags": [], "collections": ["Fine jewellery"], "image_url": "img/pearl_necklace.jpg",
     "price": "890.00", "currency": "GBP", "status": "ACTIVE", "sizes": []},
    {"id": "p3", "title": "No. 9 eau de parfum", "vendor": "Maison Aurelle", "type": "",
     "tags": ["new"], "collections": ["Fragrance"], "image_url": "img/perfume.jpg",
     "price": "165.00", "currency": "GBP", "status": "ACTIVE", "sizes": ["50ml", "100ml"]},
    {"id": "p4", "title": "Satin evening heel", "vendor": "Maison Aurelle", "type": "",
     "tags": [], "collections": ["Shoes"], "image_url": "img/wrapped_luxury_heels.jpg",
     "price": "620.00", "currency": "GBP", "status": "ACTIVE", "sizes": ["37", "38", "39", "40"]},
    {"id": "p5", "title": "Camille silk scarf", "vendor": "Maison Aurelle", "type": "",
     "tags": ["sale"], "collections": ["Accessories"], "image_url": "img/nice_necklace.jpg",
     "price": "180.00", "currency": "GBP", "status": "ACTIVE", "sizes": []},
    {"id": "p6", "title": "Oak occasional table", "vendor": "Maison Aurelle", "type": "",
     "tags": [], "collections": ["Home"], "image_url": "img/home_furniture.jpg",
     "price": "740.00", "currency": "GBP", "status": "ACTIVE", "sizes": []},
]


def main() -> None:
    html = catalog_form_html(
        {"name": "A private selection for Grace",
         "subtitle": "Chosen with you in mind. Tick anything you'd like and I'll be in touch.",
         "logo": "", "brand_color": "#5C3B54", "fields": None},
        PRODUCTS,
        shop_name="Maison Aurelle",
        catalog_id="cat_demo",
        enquiry_email="hello@example.com",
        prefill={"name": "Grace", "email": "", "phone": ""},
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}  ({len(PRODUCTS)} products, {len(html):,} bytes)")


if __name__ == "__main__":
    main()
