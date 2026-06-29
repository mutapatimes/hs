"""FastAPI service — the embedded Shopify app + the per-shop query interface.

`GET /` is the embedded entry (the dashboard inside the Shopify admin). The `/v1/*`
data routes are scoped to the authenticated shop via the App Bridge session token, so
one deployment serves many merchants without leaking data between them.

    GET  /                      — embedded dashboard (in admin.shopify.com)
    POST /v1/sync               — re-pull + re-score this shop
    GET  /v1/dashboard          — this shop's hidden VICs (JSON)
    POST /v1/score              — score a raw record (no shop; stateless helper)
    GET  /v1/score?email=       — this shop's stored score for a customer
    GET  /v1/orders/{id}/score  — the score behind an order (fulfilment lookup)
    GET  /v1/hidden-vics        — this shop's ranked hidden VICs
    GET  /fulfilment            — this shop's pick list, priority-first
    GET  /health                — liveness (open, for Render health checks)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query

from halia.api.shopify_auth import require_shop
from halia.engine import engine
from halia.store import ScoreStore

app = FastAPI(title="Halia", version="1.0", summary="Hidden-VIC scoring — embedded Shopify app")
app.state.store = None


def get_store() -> ScoreStore:
    if app.state.store is None:
        app.state.store = ScoreStore()
    return app.state.store


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/score")
def score(payload: Any = Body(...)) -> Any:
    """Score a customer record (or list) live — stateless, no shop needed."""
    if isinstance(payload, list):
        return [r.to_dict() for r in engine.score_many(payload)]
    if isinstance(payload, dict):
        return engine.score_one(payload).to_dict()
    raise HTTPException(422, "Body must be a customer record object or a list of them")


@app.get("/v1/score")
def get_score(shop: str = Depends(require_shop),
              id: Optional[str] = Query(None), email: Optional[str] = Query(None)) -> dict:
    store = get_store()
    result = store.get_by_customer_id(shop, id) if id else (
        store.get_by_email(shop, email) if email else None)
    if id is None and email is None:
        raise HTTPException(422, "Provide ?id= or ?email=")
    if result is None:
        raise HTTPException(404, "No score on file for that customer")
    return result.to_dict()


@app.get("/v1/orders/{order_id}/score")
def order_score(order_id: str, shop: str = Depends(require_shop)) -> dict:
    result = get_store().score_for_order(shop, order_id)
    if result is None:
        raise HTTPException(404, "No scored customer for that order")
    return result.to_dict()


@app.get("/v1/hidden-vics")
def hidden_vics(shop: str = Depends(require_shop),
                limit: int = Query(50, ge=1, le=1000)) -> list[dict]:
    return [r.to_dict() for r in get_store().top_hidden(shop, limit)]


# Mount the embedded entry (GET / , /v1/sync, /v1/dashboard) and the fulfilment view.
from halia.api import embedded, fulfilment  # noqa: E402

embedded.register(app, get_store)
fulfilment.register(app, get_store)
