"""Fetch customers + orders from the Shopify GraphQL Admin API, then score them.

Single-merchant CUSTOM APP path (no OAuth): in the store admin go to
Settings -> Apps -> Develop apps -> create an app, grant `read_customers`,
`read_orders`, `read_all_orders`, install it, and copy the Admin API access
token. Then set:

    SHOPIFY_SHOP=your-store.myshopify.com
    SHOPIFY_ADMIN_TOKEN=shpat_xxx
    SHOPIFY_API_VERSION=2025-01            # optional

Run:

    python -m scoring.shopify_fetch         # pulls live, prints a scoring summary

The HTTP call is injected as ``transport`` so the whole pull is unit-testable
against a fake Shopify (and can be dry-run with ``max_pages`` and no creds).

Pipeline:  Admin API ──CUSTOMERS_QUERY (paged)──▶ customer nodes
           ──graphql_customers_to_orders──▶ REST-shaped orders
           ──orders_to_customers──▶ per-customer DataFrame ──▶ score_customers
"""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Iterator

from scoring.shopify_graphql import (
    CUSTOMER_BY_QUERY,
    CUSTOMERS_QUERY,
    graphql_customers_to_orders,
)

DEFAULT_API_VERSION = "2025-01"

# A transport maps (query, variables) -> the parsed JSON response dict.
Transport = Callable[[str, dict], dict]


class ShopifyError(RuntimeError):
    """A non-retryable error returned by the Shopify Admin API."""


class ShopifyAuthError(ShopifyError):
    """The Admin API rejected the access token (revoked, uninstalled, or missing a scope).

    Distinct from ShopifyError so a caller holding the session token can re-exchange for a
    fresh offline token and retry once, instead of failing the whole load permanently.
    """


def _is_throttled(errors: object) -> bool:
    return isinstance(errors, list) and any(
        (e.get("extensions") or {}).get("code") == "THROTTLED"
        for e in errors if isinstance(e, dict)
    )


def _is_auth_error(errors: object) -> bool:
    """True when a GraphQL error set signals an auth/scope problem (revoked token, or a scope
    the token doesn't carry) — the classes a fresh token exchange can repair."""
    if isinstance(errors, str):  # Shopify returns a bare string for some auth failures
        low = errors.lower()
        return any(k in low for k in ("access token", "api key", "unauthorized", "unauthenticated"))
    if isinstance(errors, list):
        codes = {(e.get("extensions") or {}).get("code")
                 for e in errors if isinstance(e, dict)}
        return bool(codes & {"ACCESS_DENIED", "UNAUTHORIZED", "UNAUTHENTICATED"})
    return False


def _shop_domain(shop: str) -> str:
    return shop if shop.endswith(".myshopify.com") else f"{shop}.myshopify.com"


def endpoint(shop: str, version: str = DEFAULT_API_VERSION) -> str:
    return f"https://{_shop_domain(shop)}/admin/api/{version}/graphql.json"


def http_transport(
    shop: str | None = None,
    token: str | None = None,
    version: str | None = None,
    timeout: int = 30,
) -> Transport:
    """Real transport: POSTs to Shopify with the Admin API token.

    Reads SHOPIFY_SHOP / SHOPIFY_ADMIN_TOKEN / SHOPIFY_API_VERSION when the
    matching argument is omitted. ``requests`` is imported lazily so importing
    this module (and the tests) never requires it.
    """
    import requests

    shop = shop or os.environ["SHOPIFY_SHOP"]
    token = token or os.environ["SHOPIFY_ADMIN_TOKEN"]
    version = version or os.environ.get("SHOPIFY_API_VERSION", DEFAULT_API_VERSION)
    url = endpoint(shop, version)
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    def _call(query: str, variables: dict) -> dict:
        resp = requests.post(
            url, headers=headers, json={"query": query, "variables": variables}, timeout=timeout
        )
        # A revoked/invalid token gets a hard 401/403 here (before any GraphQL parsing). Surface
        # it as ShopifyAuthError so the caller can re-exchange, not a generic requests HTTPError.
        if resp.status_code in (401, 403):
            raise ShopifyAuthError(f"Admin API rejected the token (HTTP {resp.status_code})")
        resp.raise_for_status()
        return resp.json()

    return _call


def _run(transport: Transport, query: str, variables: dict, retries: int, _sleep=time.sleep) -> dict:
    """Run one query, backing off and retrying on Shopify's THROTTLED errors."""
    delay = 1.0
    for _ in range(max(1, retries)):
        payload = transport(query, variables)
        errors = payload.get("errors")
        if errors:
            if _is_throttled(errors):
                _sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if _is_auth_error(errors):
                raise ShopifyAuthError(json.dumps(errors)[:500])
            raise ShopifyError(json.dumps(errors)[:500])
        data = payload.get("data")
        if data is None:
            raise ShopifyError("Shopify response had no 'data'")
        return data
    raise ShopifyError("Exhausted retries (still throttled)")


def fetch_customer_nodes(
    transport: Transport,
    max_pages: int | None = None,
    retries: int = 5,
    _sleep=time.sleep,
) -> Iterator[dict]:
    """Page through the ``customers`` connection, yielding each customer node.

    ``max_pages`` caps the pull (useful for a dry-run); None means all pages.
    """
    cursor: str | None = None
    pages = 0
    while True:
        data = _run(transport, CUSTOMERS_QUERY, {"cursor": cursor}, retries, _sleep)
        conn = data["customers"]
        yield from conn["nodes"]
        pages += 1
        info = conn["pageInfo"]
        if not info["hasNextPage"] or (max_pages is not None and pages >= max_pages):
            break
        cursor = info["endCursor"]


def fetch_orders(transport: Transport | None = None, **kwargs) -> list[dict]:
    """Fetch all customers and return REST-shaped order dicts ready to aggregate."""
    if transport is None:
        transport = http_transport()
    nodes = list(fetch_customer_nodes(transport, **kwargs))
    return graphql_customers_to_orders(nodes)


def fetch_customer_orders(
    identifier: str,
    transport: Transport | None = None,
    by: str = "email",
    retries: int = 5,
) -> list[dict]:
    """Fetch ONE customer's orders by email/phone (the real-time / POS path).

    Returns REST-shaped order dicts for the single matching customer, or [] if
    none matched. ``by`` is "email", "phone", or "id" (the POS tile passes a
    numeric customer id, or a ``gid://shopify/Customer/123`` reduced to its tail).
    """
    if transport is None:
        transport = http_transport()
    if by == "id":
        ident = str(identifier).rsplit("/", 1)[-1]  # gid://shopify/Customer/123 -> 123
        query = f"id:{ident}"                        # Shopify search: unquoted numeric id
    else:
        query = f'{by}:"{identifier}"'               # e.g. email:"a@b.com"
    data = _run(transport, CUSTOMER_BY_QUERY, {"q": query}, retries)
    return graphql_customers_to_orders(data["customers"]["nodes"])


def fetch_scored(transport: Transport | None = None, today=None, **kwargs):
    """End-to-end: fetch -> aggregate -> score. Returns a scored DataFrame."""
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers

    orders = fetch_orders(transport, **kwargs)
    customers = orders_to_customers(orders, today=today)
    return score_customers(customers)


def main() -> None:  # pragma: no cover - live smoke test, needs credentials
    from scoring.combine import HIDDEN_COL

    scored = fetch_scored()
    print(
        f"Fetched + scored {len(scored):,} customers · "
        f"{int(scored[HIDDEN_COL].sum())} hidden VICs"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
