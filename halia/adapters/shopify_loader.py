"""Load realistic, signal-rich TEST customers + orders into a Shopify dev store.

A fresh dev store is empty, so there's nothing for Halia to score. This seeds it with
synthetic-but-realistic customers (HNW email domains, prime postcodes, honorifics, …)
each with an order, so the full Shopify → score → Klaviyo pipeline has real Shopify data
to flow through. Reuses the same identity generator as `make_synthetic_data.py`.

FOR A DEV/TEST STORE ONLY — it creates real orders via the Admin REST API. Needs the
`write_customers` and `write_orders` scopes on the custom app.

    SHOPIFY_SHOP=… SHOPIFY_ADMIN_TOKEN=… python -m halia.adapters.shopify_loader 25

The HTTP call is injectable as `transport` so the body-building is unit-testable.
"""
from __future__ import annotations

import os
import random
import time

from halia import config  # noqa: F401  — importing loads .env into os.environ
from scoring.shopify_fetch import DEFAULT_API_VERSION, _shop_domain

# Grade spread for a quick, varied test set (target grades; actual may vary slightly).
_DEFAULT_MIX = ["A1"] * 3 + ["A"] * 5 + ["B"] * 8 + ["C"] * 7 + [None] * 2


def _rest_transport(shop: str, token: str, version: str):
    import requests

    base = f"https://{_shop_domain(shop)}/admin/api/{version}"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    def _call(method: str, path: str, body: dict) -> tuple[int, dict]:
        resp = requests.request(method, f"{base}{path}", headers=headers, json=body, timeout=30)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        return resp.status_code, payload

    return _call


def _split_name(name: str) -> tuple[str, str]:
    """First word -> first_name, the rest -> last_name (Shopify needs both non-blank);
    reconstructs to the full crafted name so name signals still fire."""
    parts = str(name).split(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 and parts[1].strip() else (parts[0], parts[0])


def _address(r: dict) -> dict:
    # No phone — Shopify validates phone strictly and synthetic numbers fail.
    first, last = _split_name(r["Name"])
    return {
        "first_name": first, "last_name": last,
        "address1": r["address1"], "address2": r["address2"] or None,
        "city": r["city"], "country": r["country"] or "United Kingdom", "zip": r["zip"],
        "company": r["company"] or None,
    }


def _order_body(r: dict, price: float) -> dict:
    # Embed the customer on the order: Shopify creates/links it by email (idempotent
    # across reruns — no duplicate-email errors) and takes the name from here.
    first, last = _split_name(r["Name"])
    return {"order": {
        "customer": {"first_name": first, "last_name": last, "email": r["EMAIL_ADDR"]},
        "email": r["EMAIL_ADDR"],
        "financial_status": "paid",
        "line_items": [{"title": "Halia test order", "price": f"{price:.2f}", "quantity": 1}],
        "billing_address": _address(r), "shipping_address": _address(r),
        "inventory_behaviour": "bypass", "send_receipt": False, "send_fulfillment_receipt": False,
    }}


def generate_identities(n: int, seed: int = 7) -> list[dict]:
    """Signal-rich identities across a grade spread (reuses make_synthetic_data)."""
    import make_synthetic_data as gen

    rng = random.Random(seed)
    mix = (_DEFAULT_MIX * (n // len(_DEFAULT_MIX) + 1))[:n]
    return [gen.make_identity(rng, i, grade) for i, grade in enumerate(mix)]


class ShopifyLoader:
    def __init__(self, transport=None, version: str | None = None, pace: float = 0.4,
                 retry_429: int = 6, retry_wait: float = 35.0, max_orders_per_customer: int = 1):
        self.transport = transport
        self.version = version or os.environ.get("SHOPIFY_API_VERSION", DEFAULT_API_VERSION)
        self.pace = pace
        self.retry_429 = retry_429
        self.retry_wait = retry_wait
        # Dev/unpaid stores cap order creation per minute; keep one order per customer.
        self.max_orders = max_orders_per_customer

    def _t(self):
        if self.transport is None:
            self.transport = _rest_transport(
                os.environ["SHOPIFY_SHOP"], os.environ["SHOPIFY_ADMIN_TOKEN"], self.version)
        return self.transport

    def _post(self, path: str, body: dict) -> dict:
        from scoring.shopify_fetch import ShopifyError

        for attempt in range(self.retry_429 + 1):
            status, payload = self._t()("POST", path, body)
            if 200 <= status < 300:
                return payload
            if status == 429 and attempt < self.retry_429:  # dev-store order rate limit
                if self.retry_wait:
                    time.sleep(self.retry_wait)
                continue
            raise ShopifyError(f"POST {path} HTTP {status}: {str(payload)[:300]}")
        raise ShopifyError(f"POST {path}: exhausted 429 retries")

    def load_one(self, r: dict) -> dict:
        n_orders = min(self.max_orders, max(1, int(r.get("_orders", 1))))
        per = round(float(r.get("_spend", 0)) / n_orders, 2) or 50.0
        for _ in range(n_orders):
            self._post("/orders.json", _order_body(r, per))
            if self.pace:
                time.sleep(self.pace)
        return {"email": r["EMAIL_ADDR"], "orders": n_orders}

    def load(self, identities: list[dict]) -> dict:
        loaded, failed = [], []
        for r in identities:
            try:
                loaded.append(self.load_one(r))
            except Exception as exc:
                failed.append({"email": r.get("EMAIL_ADDR"), "error": str(exc)[:200]})
            if self.pace:
                time.sleep(self.pace)
        return {"loaded": len(loaded), "orders": sum(x["orders"] for x in loaded), "failed": failed}


def main() -> None:  # pragma: no cover - live, needs write scopes
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    print(f"Loading {n} signal-rich TEST customers + orders into {os.environ.get('SHOPIFY_SHOP')} ...")
    summary = ShopifyLoader().load(generate_identities(n))
    print(f"  loaded {summary['loaded']} customers · {summary['orders']} orders")
    if summary["failed"]:
        print(f"  {len(summary['failed'])} failed; first: {summary['failed'][0]}")
    print("Now run:  .venv/bin/python -m halia.sync shopify   (then add --sinks klaviyo --limit 20)")


if __name__ == "__main__":  # pragma: no cover
    main()
