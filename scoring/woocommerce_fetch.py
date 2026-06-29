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


def fetch_orders(
    transport: Transport,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int | None = None,
    status: str | None = None,
) -> list[dict]:
    """Page through /orders (newest first) and return the raw WooCommerce order list.

    ``status`` optionally filters (e.g. "completed" or "completed,processing"); the
    WooCommerce default returns all non-trashed orders.
    """
    orders: list[dict] = []
    page = 1
    while True:
        params = {"per_page": per_page, "page": page, "orderby": "date", "order": "desc"}
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
