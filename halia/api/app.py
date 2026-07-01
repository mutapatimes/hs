"""FastAPI service — the embedded Shopify app + per-shop query interface.

Zero-retention: customer data is read from the in-memory cache (`halia.api.data`), never a
database. `/v1/*` reads are scoped to the authenticated shop via the App Bridge session token.

    GET  /                      — embedded dashboard (in admin.shopify.com)
    POST /v1/sync               — re-pull + re-score this shop (into RAM)
    GET  /v1/dashboard          — this shop's hidden VICs (JSON)
    POST /v1/score              — score a raw record (stateless helper)
    GET  /v1/score?email=       — this shop's score for a customer (from RAM)
    GET  /v1/orders/{id}/score  — the score behind an order (fulfilment lookup)
    GET  /v1/hidden-vics        — this shop's ranked hidden VICs
    GET  /fulfilment            — this shop's pick list, priority-first
    POST /webhooks/*            — Shopify compliance + uninstall (HMAC-verified)
    GET  /health                — liveness (open, for Render health checks)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query

from halia.api import data
from halia.api.shopify_auth import require_shop
from halia.engine import engine

app = FastAPI(title="Halia", version="1.0", summary="Hidden-VIC scoring — embedded Shopify app")

# Serve the marketing site's imagery (water hero video, editorial photography) at /img.
from config import ROOT as _ROOT  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_IMG_DIR = _ROOT / "web" / "site" / "img"
if _IMG_DIR.is_dir():
    app.mount("/img", StaticFiles(directory=str(_IMG_DIR)), name="img")

# Shared brand layer (logo spin + asterisk design language) used by every page.
_STATIC_DIR = _ROOT / "web" / "site" / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Static legal / overview pages (Privacy, Terms, Cookies, Security).
from fastapi.responses import HTMLResponse as _HTML  # noqa: E402

_SITE_DIR = _ROOT / "web" / "site"


def _serve_page(name: str) -> _HTML:
    # Marketing pages live in web/site/, plain legal pages in web/site/legal/.
    for f in (_SITE_DIR / f"{name}.html", _SITE_DIR / "legal" / f"{name}.html"):
        if f.is_file():
            return _HTML(f.read_text(encoding="utf-8"))
    raise HTTPException(404, "Page not found")


for _name in ("solutions", "security", "clienteling", "faq", "demo", "brand",
              "responsible", "pricing", "privacy", "terms", "cookies"):
    app.add_api_route(f"/{_name}", (lambda n: lambda: _serve_page(n))(_name),
                      methods=["GET"], include_in_schema=False, response_class=_HTML)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/subscribe", include_in_schema=False)
def subscribe(payload: Any = Body(...)) -> dict:
    """Marketing-site newsletter signup. Stores just the email."""
    from halia.api.shopify_auth import shop_store

    email = str((payload or {}).get("email", "")).strip().lower()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 200:
        raise HTTPException(422, "Enter a valid email address.")
    shop_store().add_subscriber(email)
    return {"ok": True}


@app.post("/v1/score")
def score(payload: Any = Body(...)) -> Any:
    """Score a customer record (or list) live — stateless, no shop, nothing stored."""
    if isinstance(payload, list):
        return [r.to_dict() for r in engine.score_many(payload)]
    if isinstance(payload, dict):
        return engine.score_one(payload).to_dict()
    raise HTTPException(422, "Body must be a customer record object or a list of them")


def _entry(shop: str) -> dict:
    entry = data.results_for(shop)
    if entry is None:
        raise HTTPException(404, "No scored data for this shop yet — open the dashboard first.")
    return entry


@app.get("/v1/score")
def get_score(shop: str = Depends(require_shop),
              id: Optional[str] = Query(None), email: Optional[str] = Query(None)) -> dict:
    if id is None and email is None:
        raise HTTPException(422, "Provide ?id= or ?email=")
    entry = _entry(shop)
    result = data.result_by_id(entry, id) if id else data.result_by_email(entry, email)
    if result is None:
        raise HTTPException(404, "No score on file for that customer")
    return result.to_dict()


@app.get("/v1/orders/{order_id}/score")
def order_score(order_id: str, shop: str = Depends(require_shop)) -> dict:
    result = data.score_for_order(_entry(shop), order_id)
    if result is None:
        raise HTTPException(404, "No scored customer for that order")
    return result.to_dict()


@app.get("/v1/hidden-vics")
def hidden_vics(shop: str = Depends(require_shop),
                limit: int = Query(50, ge=1, le=1000)) -> list[dict]:
    return [r.to_dict() for r in data.hidden_results(_entry(shop), limit)]


@app.get("/v1/alerts")
def alerts(shop: str = Depends(require_shop),
           grades: str = Query("A*,A")) -> list[dict]:
    """Recent orders from A*/A hidden VICs — powers the live alerts feed + desktop pings.

    Merges real-time webhook alerts (RAM) with the recent high-grade orders derived from the
    last scored pull, so the feed is populated even before the first webhook fires.
    """
    from halia.cache import cache

    wanted = tuple(g.strip() for g in grades.split(",") if g.strip()) or ("A*", "A")
    ram = [a for a in cache.get_alerts(shop) if a.get("grade") in wanted]
    entry = data.results_for(shop)
    derived = data.high_grade_orders(entry, wanted) if entry else []
    seen = {a.get("order_id") for a in ram}
    return (ram + [d for d in derived if d.get("order_id") not in seen])[:40]


@app.get("/v1/export")
def export_csv(shop: str = Depends(require_shop)):
    """Download the surfaced hidden VICs as CSV, built from the in-RAM scored data (no re-fetch)."""
    import csv
    import io

    from fastapi.responses import Response

    entry = data.results_for(shop)
    rows = ((entry or {}).get("payload") or {}).get("data") or []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Email", "Phone", "Location", "Grade", "Score", "Current spend",
                "Latent value", "Signal count", "Signals", "Recommended approach"])
    for c in rows:
        signals = "; ".join(s.get("d", "") for s in (c.get("signals") or []))
        w.writerow([c.get("name", ""), c.get("email", ""), c.get("phone", ""), c.get("loc", ""),
                    c.get("grade", ""), c.get("score", ""), c.get("spend", ""), c.get("latent", ""),
                    c.get("count", len(c.get("signals") or [])), signals, c.get("reco", "")])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=halia-hidden-vics.csv"})


# Mount the embedded entry, self-service onboarding, Klaviyo + Shopify write-back, fulfilment
# view, and compliance webhooks.
from halia.api import (  # noqa: E402
    billing, embedded, fulfilment, integrations, mailchimp_integration, onboarding, realtime,
    settings, shopify_push, webhooks,
)

embedded.register(app)
onboarding.register(app)
integrations.register(app)
mailchimp_integration.register(app)
realtime.register(app)
settings.register(app)
fulfilment.register(app)
webhooks.register(app)
billing.register(app)
shopify_push.register(app)
