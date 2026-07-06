"""POST /v1/shopify/segment — turn a dashboard selection into a native Shopify customer segment.

Tags the selected customers with a unique `Halia:<slug>` tag, then creates a segment querying that
tag, so the merchant can target it as the audience in Shopify Email and send natively. Shopify has no
API for an app to *send* the campaign — the merchant sends. Shopify tenants only (needs the admin
token + the write_customers scope Halia already holds). Reads customers from the RAM cache only.
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import Body, Depends, HTTPException

from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:40] or "selection"


def register(app) -> None:

    @app.post("/v1/shopify/segment")
    def shopify_segment(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        store = shop_store()
        tenant = store.get_tenant(shop)
        if tenant and tenant["kind"] in ("woocommerce", "bigcommerce"):
            raise HTTPException(400, "Creating segments is a Shopify feature — this store is not on Shopify.")
        token = store.get_token(shop)
        if not token:
            raise HTTPException(400, "No Shopify connection for this store.")
        entry = data.results_for(shop)
        if entry is None:
            raise HTTPException(404, "No scored data for this shop yet — open the dashboard first.")
        ids = (payload or {}).get("customer_ids") or []
        name = str((payload or {}).get("name") or "").strip() or "Halia selection"
        targets = [r for r in (data.result_by_id(entry, c) for c in ids) if r and r.customer_id]
        if not targets:
            raise HTTPException(400, "No customers selected.")

        from halia.adapters.shopify_segments import create_segment, segment_numeric_id
        from halia.adapters.shopify_sink import ShopifySink
        from scoring.shopify_fetch import ShopifyError, http_transport

        tag = f"Halia:{_slug(name)}"
        transport = http_transport(shop, token)
        sink = ShopifySink(transport=transport)
        try:
            for r in targets:                       # tag exactly the selection, so the segment matches it
                sink.tag_customer(r.customer_id, [tag])
            seg = create_segment(transport, name, f"customer_tags CONTAINS '{tag}'")
        except ShopifyError as exc:
            raise HTTPException(502, f"Shopify rejected it: {exc}")

        num = segment_numeric_id(seg.get("id") or "")
        admin_url = f"https://{shop}/admin/customers/segments/{num}" if num else ""
        data.record_activity(shop, "action_shopify_segment")
        return {"segment": seg, "count": len(targets), "admin_url": admin_url}
