"""Associate-feedback loop — one-tap "good call" / "not a fit" on a surfaced VIC.

This is the bridge from heuristic weights to learned ones. Calibrating on *spend* is biased
against Halia's own thesis (see scoring/calibrate.py); calibrating on whether a surfaced VIC was
actually a good call is the real fix — and it produces labelled outcomes within weeks. Two things
happen on feedback, both zero-retention-preserving:

  1. Halia records an AGGREGATE per-signal tally only — how often each signal appeared on a
     "good call" vs a "not a fit" (store.record_feedback). No customer identifier is stored.
  2. The per-customer verdict is written back as a tag in the merchant's OWN Shopify
     ("Halia: strong lead" / "Halia: not a fit"), so the label lives merchant-side.

    POST /v1/feedback  {customer_id | email, verdict: 'fit'|'nofit'}
    GET  /v1/feedback/stats   — the aggregate tally (feeds future outcome-based calibration)
"""
from __future__ import annotations

import traceback
from typing import Any

from fastapi import Body, Depends, HTTPException

from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store

_TAG = {"fit": "Halia: strong lead", "nofit": "Halia: not a fit"}


def register(app) -> None:

    @app.post("/v1/feedback")
    def submit_feedback(shop: str = Depends(require_shop), payload: Any = Body(...)) -> dict:
        p = payload or {}
        verdict = "fit" if str(p.get("verdict")) == "fit" else (
            "nofit" if str(p.get("verdict")) == "nofit" else None)
        if verdict is None:
            raise HTTPException(422, "verdict must be 'fit' or 'nofit'.")

        entry = data.results_for(shop)
        if entry is None:
            raise HTTPException(404, "No scored data for this shop yet.")
        cid, email = p.get("customer_id"), p.get("email")
        result = (data.result_by_id(entry, cid) if cid
                  else data.result_by_email(entry, email) if email else None)
        if result is None:
            raise HTTPException(404, "Customer not found in the current scored set.")

        # 1) Aggregate, non-identifying tally — the calibration training signal.
        shop_store().record_feedback(shop, list(result.signals or []), verdict)

        # 2) Best-effort merchant-side tag (Shopify only; the label lives in THEIR system).
        tagged = False
        tenant = shop_store().get_tenant(shop)
        token = shop_store().get_token(shop)
        if result.customer_id and token and not (
                tenant and tenant["kind"] in ("woocommerce", "bigcommerce")):
            try:
                from halia.adapters.shopify_sink import ShopifySink
                from scoring.shopify_fetch import http_transport
                ShopifySink(transport=http_transport(shop, token)).tag_customer(
                    result.customer_id, [_TAG[verdict]])
                tagged = True
            except Exception:  # noqa: BLE001 — tag is a nicety; the tally is what matters
                traceback.print_exc()
        return {"ok": True, "verdict": verdict, "tagged": tagged}

    @app.get("/v1/feedback/stats")
    def feedback_stats(shop: str = Depends(require_shop)) -> dict:
        """Per-signal precision from associate feedback (fit / (fit+nofit)), richest first."""
        rows = shop_store().get_feedback_stats(shop)
        for r in rows:
            total = (r.get("fit", 0) or 0) + (r.get("nofit", 0) or 0)
            r["precision"] = round((r.get("fit", 0) or 0) / total, 3) if total else None
        rows.sort(key=lambda r: ((r["precision"] is not None), r["precision"] or 0), reverse=True)
        return {"stats": rows}
