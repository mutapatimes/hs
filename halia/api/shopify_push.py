"""Per-shop Shopify write-back — tag scored customers + set Halia metafields, from the dashboard.

Reads the scored customers from the RAM cache (never a database) and writes them back into the
merchant's own Shopify via the ShopifySink (Admin GraphQL `tagsAdd` + `metafieldsSet`), so the
Halia grade shows up where they already work — customer tags, segments, Flow, POS.

Requires the `write_customers` scope on the shop's token. A read-only token (older installs) yields
a clear "reconnect with write_customers" message rather than a 500.

    POST /v1/shopify/push {customer_ids?} — tag all hidden VICs, or a chosen few
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, HTTPException

from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store


def _entry_or_404(shop: str) -> dict:
    entry = data.results_for(shop)
    if entry is None:
        raise HTTPException(404, "No scored data for this shop yet — open the dashboard first.")
    return entry


def register(app) -> None:

    @app.post("/v1/shopify/push")
    def shopify_push(shop: str = Depends(require_shop), payload: Any = Body(None)) -> dict:
        """Write `Halia:{grade}` tags + `halia.*` metafields back to the shop's customers."""
        store = shop_store()
        tenant = store.get_tenant(shop)
        if tenant and tenant["kind"] in ("woocommerce", "bigcommerce"):
            raise HTTPException(400, "Tagging back is a Shopify feature — this store is not on Shopify.")
        token = store.get_token(shop)
        if not token:
            raise HTTPException(400, "No Shopify connection for this store.")

        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") if isinstance(payload, dict) else None
        results = [data.result_by_id(entry, c) for c in ids] if ids else data.hidden_results(entry)
        targets = [r for r in results if r and r.flagged and r.customer_id]
        if not targets:
            return {"pushed": 0}

        from halia.adapters.shopify_sink import ShopifySink
        from scoring.shopify_fetch import ShopifyError, http_transport

        try:
            ShopifySink(transport=http_transport(shop, token)).push_many(targets)
        except ShopifyError as exc:
            msg = str(exc)
            if any(t in msg.lower() for t in ("write_customers", "scope", "access denied", "403")):
                raise HTTPException(
                    400, "Reconnect Shopify with the write_customers permission to tag customers.")
            raise HTTPException(502, f"Shopify rejected the write: {msg}")
        return {"pushed": len(targets)}
