"""Pull orders from the Centra GraphQL Integration API for scoring.

Read-only path (no OAuth): in the Centra admin (AMS) go to System -> API Tokens and create an
**Integration API token** restricted to ``Order:read``. Centra instances are per-merchant, so the
merchant supplies their instance base URL plus that token:

    CENTRA_BASE_URL=https://<instance>.centra.com
    CENTRA_API_TOKEN=xxxx

The Integration API lives at ``{base}/graphql`` and authenticates with a Bearer header. Orders come
from the ``orderConnection`` query with cursor pagination (``pageInfo.hasNextPage`` /
``endCursor``), the same shape as our Shopify GraphQL pull.

The HTTP call is injected as ``transport`` so the whole pull is unit-testable against a fake
Centra (and importing this module never requires ``requests``).

NOTE on the query: ``ORDER_QUERY`` selects the conservative field set the adapter needs. GraphQL
rejects unknown fields outright, so if a live instance's schema names differ (the likely suspects
are ``zip`` vs ``zipCode`` and ``phoneNumber`` vs ``phone``), adjust the constant here — the
adapter in scoring/centra.py already tolerates either spelling.
"""
from __future__ import annotations

import os
from typing import Callable

DEFAULT_PAGE_SIZE = 100

# A transport maps (query, variables) -> the parsed GraphQL "data" dict.
Transport = Callable[[str, dict], dict]


class CentraError(RuntimeError):
    """A non-retryable error from the Centra Integration API."""


class CentraAuthError(CentraError):
    """The token was rejected (revoked/expired) — surface separately so callers can re-prompt."""


def endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/graphql"


ORDER_QUERY = """
query HaliaOrders($first: Int!, $after: String) {
  orderConnection(first: $first, after: $after, where: { storeType: DIRECT_TO_CONSUMER }) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      number
      status
      orderDate
      grandTotal { value }
      customer { email firstName lastName }
      billingAddress {
        firstName lastName companyName address1 address2 city zip country { code } phoneNumber email
      }
      shippingAddress {
        firstName lastName address1 address2 city zip country { code }
      }
      lines { quantity }
    } }
  }
}
"""


def http_transport(
    base_url: str | None = None,
    api_token: str | None = None,
    timeout: int = 60,
) -> Transport:
    """Real transport: POSTs GraphQL to Centra with a Bearer token over HTTPS.

    Reads CENTRA_BASE_URL / CENTRA_API_TOKEN when the matching argument is omitted.
    ``requests`` is imported lazily. Raises CentraAuthError on 401/403 and CentraError when
    the response carries GraphQL errors.
    """
    import requests

    base = base_url or os.environ["CENTRA_BASE_URL"]
    token = api_token or os.environ["CENTRA_API_TOKEN"]

    def _call(query: str, variables: dict) -> dict:
        resp = requests.post(
            endpoint(base),
            json={"query": query, "variables": variables},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code in (401, 403):
            raise CentraAuthError(f"Centra rejected the API token (HTTP {resp.status_code}).")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            msgs = "; ".join(str(e.get("message", e)) for e in payload["errors"])
            if "access" in msgs.lower() or "auth" in msgs.lower() or "permission" in msgs.lower():
                raise CentraAuthError(f"Centra authorisation error: {msgs}")
            raise CentraError(f"Centra GraphQL error: {msgs}")
        return payload.get("data") or {}

    return _call


def fetch_orders(
    transport: Transport,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
) -> list[dict]:
    """Cursor-page through orderConnection (DTC orders) and return the raw order nodes."""
    orders: list[dict] = []
    cursor: str | None = None
    pages = 0
    while True:
        data = transport(ORDER_QUERY, {"first": page_size, "after": cursor})
        conn = (data or {}).get("orderConnection") or {}
        edges = conn.get("edges") or []
        for edge in edges:
            node = (edge or {}).get("node")
            if isinstance(node, dict):
                orders.append(node)
        pages += 1
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage") or not edges:
            break
        cursor = info.get("endCursor")
        if not cursor:
            break
        if max_pages and pages >= max_pages:
            break
    return orders
