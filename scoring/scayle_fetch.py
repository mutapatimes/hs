"""Pull orders from the SCAYLE Admin API (JSON REST) for scoring.

Read-only path (no OAuth): in the SCAYLE Panel create an Admin API token, then the merchant
supplies their API base URL plus that token:

    SCAYLE_BASE_URL=https://<tenant-host>     # the Admin API lives under /api/admin/v1
    SCAYLE_ACCESS_TOKEN=xxxx

Auth is the ``X-Access-Token`` header. Orders come from ``/api/admin/v1/orders`` with cursor
pagination (``limit`` + ``cursor``; the next cursor is carried in the response envelope), the same
read-and-page shape as our BigCommerce / Centra pulls.

The HTTP call is injected as ``transport`` so the whole pull is unit-testable against a fake SCAYLE
(and importing this module never requires ``requests``).

NOTE: scayle.dev renders its API reference client-side, so the exact envelope keys and order field
names were not scrapable at build time. ``_extract`` tolerates the common list-envelope shapes and
``scoring/scayle.py`` tolerates field-name variants; validate ``ORDERS_PATH``, the cursor key, and
the money convention against a real instance (see scoring/scayle.py).
"""
from __future__ import annotations

import os
from typing import Callable

DEFAULT_PAGE_SIZE = 100
API_PREFIX = "api/admin/v1"
ORDERS_PATH = "orders"

# A transport maps (path, params) -> parsed JSON (an envelope dict, or a bare list).
Transport = Callable[[str, dict], object]


class ScayleError(RuntimeError):
    """A non-retryable error from the SCAYLE Admin API."""


class ScayleAuthError(ScayleError):
    """The access token was rejected (401/403) — surface separately so callers can re-prompt."""


def endpoint(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + API_PREFIX + "/" + path.lstrip("/")


def http_transport(
    base_url: str | None = None,
    access_token: str | None = None,
    timeout: int = 60,
) -> Transport:
    """Real transport: GETs from the SCAYLE Admin API with the X-Access-Token header over HTTPS.

    Reads SCAYLE_BASE_URL / SCAYLE_ACCESS_TOKEN when the matching argument is omitted.
    ``requests`` is imported lazily. Raises ScayleAuthError on 401/403.
    """
    import requests

    base = base_url or os.environ["SCAYLE_BASE_URL"]
    token = access_token or os.environ["SCAYLE_ACCESS_TOKEN"]

    def _call(path: str, params: dict) -> object:
        resp = requests.get(
            endpoint(base, path),
            params=params or {},
            headers={"X-Access-Token": token, "Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code in (401, 403):
            raise ScayleAuthError(f"SCAYLE rejected the access token (HTTP {resp.status_code}).")
        resp.raise_for_status()
        return resp.json()

    return _call


def _extract(envelope: object) -> tuple[list, object]:
    """Return (items, next_cursor) from a SCAYLE list response, tolerating envelope shapes.

    Handles a bare list, or a dict whose items live under data/entities/items/collection and whose
    next cursor lives under cursor / pagination.next / paging.next / a top-level next|nextCursor.
    """
    if isinstance(envelope, list):
        return envelope, None
    if not isinstance(envelope, dict):
        return [], None
    items = envelope.get("data")
    if not isinstance(items, list):
        items = (envelope.get("entities") or envelope.get("items")
                 or envelope.get("collection") or [])
    cursor = None
    for key in ("cursor", "pagination", "paging", "page"):
        holder = envelope.get(key)
        if isinstance(holder, dict):
            cursor = (holder.get("next") or holder.get("cursor")
                      or holder.get("nextCursor") or holder.get("after"))
        elif isinstance(holder, str) and key == "cursor":
            cursor = holder
        if cursor:
            break
    if not cursor:
        cursor = envelope.get("next") or envelope.get("nextCursor")
    return (items if isinstance(items, list) else []), cursor


def fetch_orders(
    transport: Transport,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    path: str = ORDERS_PATH,
) -> list[dict]:
    """Cursor-page through the orders list and return the raw order dicts."""
    orders: list[dict] = []
    cursor: object = None
    pages = 0
    while True:
        params: dict = {"limit": page_size}
        if cursor:
            params["cursor"] = cursor
        items, cursor = _extract(transport(path, params))
        orders.extend(o for o in items if isinstance(o, dict))
        pages += 1
        if not cursor or not items:
            break
        if max_pages and pages >= max_pages:
            break
    return orders
