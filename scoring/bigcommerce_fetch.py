"""Pull orders from the BigCommerce REST API for scoring.

Read-only path (no OAuth): in the store control panel go to Settings -> API accounts ->
Create API account, grant **Orders** and **Customers** read-only, and copy the Access Token
plus the store hash (the code in the API path api.bigcommerce.com/stores/<hash>/). Then:

    BIGCOMMERCE_STORE_HASH=abc12def
    BIGCOMMERCE_ACCESS_TOKEN=xxxx

The HTTP call is injected as ``transport`` so the whole pull is unit-testable against a fake
BigCommerce (and importing this module never requires ``requests``).

Uses the v2 Orders API, which returns a bare JSON array (and HTTP 204 when a page is empty).
"""
from __future__ import annotations

import os
from typing import Callable

DEFAULT_PER_PAGE = 250  # BigCommerce v2 max page size

# A transport maps (path, params) -> parsed JSON (a list of orders for "orders").
Transport = Callable[[str, dict], object]


class BigCommerceError(RuntimeError):
    """A non-retryable error from the BigCommerce REST API."""


def endpoint(store_hash: str, path: str = "orders", version: str = "v2") -> str:
    return f"https://api.bigcommerce.com/stores/{store_hash}/{version}/{path}"


def http_transport(
    store_hash: str | None = None,
    access_token: str | None = None,
    timeout: int = 30,
) -> Transport:
    """Real transport: GETs from BigCommerce with the X-Auth-Token header over HTTPS.

    Reads BIGCOMMERCE_STORE_HASH / BIGCOMMERCE_ACCESS_TOKEN when the matching argument is
    omitted. ``requests`` is imported lazily. Returns [] on a 204 (empty page).
    """
    import requests

    store_hash = store_hash or os.environ["BIGCOMMERCE_STORE_HASH"]
    token = access_token or os.environ["BIGCOMMERCE_ACCESS_TOKEN"]

    def _call(path: str, params: dict) -> object:
        resp = requests.get(endpoint(store_hash, path), params=params,
                            headers={"X-Auth-Token": token, "Accept": "application/json"},
                            timeout=timeout)
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return resp.json()

    return _call


def fetch_orders(
    transport: Transport,
    per_page: int = DEFAULT_PER_PAGE,
    max_pages: int | None = None,
    status_id: int | None = None,
) -> list[dict]:
    """Page through /orders (newest first) and return the raw BigCommerce order list.

    Accepts either the v2 bare-array response or a {"data": [...]} envelope. ``status_id``
    optionally filters by BigCommerce order status; the default returns all orders.
    """
    orders: list[dict] = []
    page = 1
    while True:
        params: dict = {"limit": per_page, "page": page, "sort": "date_created:desc"}
        if status_id is not None:
            params["status_id"] = status_id
        batch = transport("orders", params)
        if isinstance(batch, dict):
            batch = batch.get("data") or []
        if not isinstance(batch, list):
            raise BigCommerceError(f"Unexpected BigCommerce response: {batch!r}")
        if not batch:
            break
        orders.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
        if max_pages and page > max_pages:
            break
    return orders


def fetch_order_products(transport: Transport, order_id: object,
                         per_page: int = DEFAULT_PER_PAGE) -> list[dict]:
    """Line items of one order via /orders/{id}/products (v2 has no inline products array).

    Used to put item names on the 'open basket' panel; BigCommerce incomplete orders
    (status_id 0) are carts that reached checkout but weren't paid.
    """
    out: list[dict] = []
    page = 1
    while True:
        batch = transport(f"orders/{order_id}/products", {"limit": per_page, "page": page})
        if isinstance(batch, dict):
            batch = batch.get("data") or []
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return out
