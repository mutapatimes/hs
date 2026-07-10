"""Pull orders from the WooCommerce REST API (v3) for scoring.

Read-only path (no OAuth): in the store's WP admin go to
WooCommerce -> Settings -> Advanced -> REST API -> Add key, set permission to
**Read**, and copy the Consumer key (ck_...) + Consumer secret (cs_...). Then set:

    WOO_STORE_URL=https://store.example.com
    WOO_CONSUMER_KEY=ck_xxx
    WOO_CONSUMER_SECRET=cs_xxx

The HTTP call is injected as ``transport`` so the whole pull is unit-testable
against a fake WooCommerce (and importing this module never requires ``requests``).
"""
from __future__ import annotations

import os
from typing import Callable

DEFAULT_PER_PAGE = 100

# Only the fields the scorer reads (scoring.woocommerce.woo_order_to_rest). Passing `_fields`
# to WooCommerce makes each page far smaller and faster: it drops meta_data, tax/fee/coupon
# lines, refunds, etc. that a full order object carries. This alone can cut a large-store pull
# from many minutes to a fraction of that.
ORDER_FIELDS = ("id,customer_id,status,total,discount_total,date_created_gmt,date_created,"
                "billing,shipping,line_items")

# A transport maps (path, params) -> parsed JSON (a list of orders for "orders").
Transport = Callable[[str, dict], object]


class WooError(RuntimeError):
    """A non-retryable error from the WooCommerce REST API."""


def _base(url: str) -> str:
    return url.rstrip("/")


def endpoint(store_url: str, path: str = "orders", version: str = "wc/v3") -> str:
    return f"{_base(store_url)}/wp-json/{version}/{path}"


def http_transport(
    store_url: str | None = None,
    consumer_key: str | None = None,
    consumer_secret: str | None = None,
    timeout: int = 30,
) -> Transport:
    """Real transport: GETs from WooCommerce with HTTP Basic (key/secret) over HTTPS.

    Reads WOO_STORE_URL / WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET when the matching
    argument is omitted. ``requests`` is imported lazily.
    """
    import requests

    store_url = store_url or os.environ["WOO_STORE_URL"]
    ck = consumer_key or os.environ["WOO_CONSUMER_KEY"]
    cs = consumer_secret or os.environ["WOO_CONSUMER_SECRET"]

    def _call(path: str, params: dict) -> object:
        resp = requests.get(endpoint(store_url, path), params=params, auth=(ck, cs), timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    return _call


# ── Products (for the catalogue builder — the Woo equivalent of scoring.shopify_fetch.fetch_products)
import html as _html  # noqa: E402
import re as _re  # noqa: E402

PRODUCT_FIELDS = ("id,name,slug,type,status,sku,price,regular_price,description,"
                  "short_description,images,categories,tags,variations")


def _strip_html(s: str) -> str:
    return _re.sub(r"\s+", " ", _html.unescape(_re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


def _product_to_dict(p: dict, currency: str = "") -> dict:
    """A WooCommerce product -> the same flat dict the catalogue uses (shared with Shopify)."""
    imgs = p.get("images") or []
    return {
        "id": str(p.get("id")),
        "title": p.get("name") or "Untitled",
        "handle": p.get("slug"),
        "vendor": "",                                   # WooCommerce has no native vendor
        "type": p.get("type") or "",
        "tags": [t.get("name") for t in (p.get("tags") or []) if t.get("name")],
        "collections": [c.get("name") for c in (p.get("categories") or []) if c.get("name")],
        "image_url": imgs[0].get("src") if imgs else None,
        "price": p.get("price") or p.get("regular_price") or "",
        "currency": currency,
        "status": "ACTIVE" if p.get("status") == "publish" else str(p.get("status") or "").upper(),
        "description": _strip_html(p.get("description") or p.get("short_description") or "")[:400],
        "sku": p.get("sku") or "",
        "variants": len(p.get("variations") or []),
    }


def _store_currency(transport: Transport) -> str:
    try:
        data = transport("data/currencies/current", {})
        return (data.get("code") or "") if isinstance(data, dict) else ""
    except Exception:  # noqa: BLE001 — currency is a nicety; a missing one just drops the symbol
        return ""


def fetch_products(transport: Transport, per_page: int = DEFAULT_PER_PAGE,
                   max_pages: int | None = None) -> list[dict]:
    """Page through /products (published only) and return catalogue-shaped product dicts."""
    currency = _store_currency(transport)
    out: list[dict] = []
    page = 1
    while True:
        batch = transport("products", {"per_page": per_page, "page": page,
                                       "status": "publish", "_fields": PRODUCT_FIELDS})
        if not isinstance(batch, list):
            raise WooError(f"Unexpected WooCommerce response: {batch!r}")
        if not batch:
            break
        out.extend(_product_to_dict(p, currency) for p in batch)
        if len(batch) < per_page:
            break
        page += 1
        if max_pages and page > max_pages:
            break
    return out


def fetch_orders(
    transport: Transport,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int | None = None,
    status: str | None = None,
    fields: str | None = ORDER_FIELDS,
) -> list[dict]:
    """Page through /orders (newest first) and return the raw WooCommerce order list.

    ``status`` optionally filters (e.g. "completed" or "completed,processing"); the
    WooCommerce default returns all non-trashed orders. ``fields`` limits the response to
    the columns the scorer needs (pass None for full order objects).
    """
    orders: list[dict] = []
    page = 1
    while True:
        params = {"per_page": per_page, "page": page, "orderby": "date", "order": "desc"}
        if fields:
            params["_fields"] = fields
        if status:
            params["status"] = status
        batch = transport("orders", params)
        if not isinstance(batch, list):
            raise WooError(f"Unexpected WooCommerce response: {batch!r}")
        if not batch:
            break
        orders.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        if max_pages and page > max_pages:
            break
    return orders
