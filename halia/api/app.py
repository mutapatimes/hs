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

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request

from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store
from halia.engine import engine
from halia.reference_bundle import unpack as _unpack_reference_bundle

# Restore the operator's git-ignored high-precision reference tables (company controllers, charity
# trustees, US insiders) from the committed encrypted bundle, so those signals load in production.
# No-op in dev where the real .local tables already exist, and when no key / no bundle is present.
_restored = _unpack_reference_bundle()
if _restored:
    print(f"reference bundle: restored {len(_restored)} private table(s): {', '.join(_restored)}")

# Swagger UI is relocated off /docs so the marketing documentation page can own that path.
app = FastAPI(title="Halia", version="1.0", summary="Hidden-VIC scoring — embedded Shopify app",
              docs_url="/api/docs", openapi_url="/api/openapi.json")

# The POS UI extension calls this backend cross-origin from the Shopify POS webview.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://cdn.shopify.com", "https://extensions.shopifycdn.com"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Lightweight per-IP rate limiting on the sensitive endpoints ─────────────────────
# In-process fixed window: guards auth/scoring/onboarding against brute-force + hammering.
# Single-instance (fine on Render free); a reverse proxy / WAF is the proper control at
# scale. Disabled under pytest (per-request check) so the test suite can't trip it; set
# HALIA_RATE_LIMIT=0 to turn it off in prod if ever needed.
import os as _os  # noqa: E402
import time as _time  # noqa: E402
from collections import deque as _deque  # noqa: E402

from fastapi.responses import JSONResponse as _JSONResponse  # noqa: E402

_RL_WINDOW = 60.0
_RL_MAX = {"r": 120, "w": 30}   # requests per IP per window: reads (GET/HEAD) vs writes
_RL_HITS: dict = {}
_RL_PATHS = ("/v1/", "/app", "/connect", "/subscribe", "/webhooks")


def _rate_limited(ip: str, write: bool, now: float | None = None) -> bool:
    """True if this IP has exceeded its window for reads/writes. Pure + unit-testable."""
    now = _time.monotonic() if now is None else now
    if len(_RL_HITS) > 5000:          # crude memory bound: reset rather than grow unbounded
        _RL_HITS.clear()
    key = f"{ip}|{'w' if write else 'r'}"
    dq = _RL_HITS.setdefault(key, _deque())
    cutoff = now - _RL_WINDOW
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= _RL_MAX["w" if write else "r"]:
        return True
    dq.append(now)
    return False


@app.middleware("http")
async def _rate_limit_mw(request, call_next):
    if ("PYTEST_CURRENT_TEST" in _os.environ or _os.environ.get("HALIA_RATE_LIMIT") == "0"
            or request.method == "OPTIONS"):
        return await call_next(request)
    path = request.url.path
    if any(path.startswith(p) for p in _RL_PATHS):
        ip = request.client.host if request.client else "?"
        if _rate_limited(ip, request.method not in ("GET", "HEAD")):
            return _JSONResponse({"detail": "Too many requests — please slow down."},
                                 status_code=429, headers={"Retry-After": "60"})
    return await call_next(request)

# Serve the marketing site's imagery (water hero video, editorial photography) at /img.
from config import ROOT as _ROOT  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402


class _RevalidateStatic(StaticFiles):
    """Serve CSS/JS with ``Cache-Control: no-cache`` so browsers must revalidate against
    the ETag before reusing a cached copy. Files still get a 304 when unchanged (cheap), but
    a deploy that rewrites brand.css/brand.js is picked up immediately instead of a stale copy
    lingering — which otherwise breaks the shared footer/nav when class names change."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


_IMG_DIR = _ROOT / "web" / "site" / "img"
if _IMG_DIR.is_dir():
    app.mount("/img", StaticFiles(directory=str(_IMG_DIR)), name="img")

# Shared brand layer (logo spin + asterisk design language) used by every page.
_STATIC_DIR = _ROOT / "web" / "site" / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", _RevalidateStatic(directory=str(_STATIC_DIR)), name="static")

# Static legal / overview pages (Privacy, Terms, Cookies, Security).
from fastapi.responses import HTMLResponse as _HTML  # noqa: E402

_SITE_DIR = _ROOT / "web" / "site"


def _serve_page(name: str) -> _HTML:
    # Marketing pages live in web/site/, plain legal pages in web/site/legal/.
    from halia.api.content import apply_overrides, with_site_scripts
    for f in (_SITE_DIR / f"{name}.html", _SITE_DIR / "legal" / f"{name}.html"):
        if f.is_file():
            html = with_site_scripts(apply_overrides(f.read_text(encoding="utf-8")))
            # Any page carrying the corporate small print (Midnight Lantern) is kept out of
            # search — a noindex header on top of the page's meta tag, applied by content so it
            # covers any future page too.
            headers = {"X-Robots-Tag": "noindex, nofollow"} if "Midnight Lantern" in html else None
            return _HTML(html, headers=headers)
    raise HTTPException(404, "Page not found")


for _name in ("solutions", "security", "clienteling", "faq", "demo", "brand",
              "responsible", "pricing", "privacy", "terms", "cookies", "subprocessors",
              "status"):
    app.add_api_route(f"/{_name}", (lambda n: lambda: _serve_page(n))(_name),
                      methods=["GET"], include_in_schema=False, response_class=_HTML)


# ---- The decks (/pitch, /present, /present-brands): password-gated, never indexed. ----------
# A shared password (rotatable via env) gates all three; entering it once sets a signed
# cookie for 30 days. The cookie is a hash OF the password, so it proves knowledge of it
# and a captured cookie never reveals it. Every response carries X-Robots-Tag: noindex.
import hashlib as _hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402
from fastapi.responses import RedirectResponse as _Redirect  # noqa: E402

_DECKS = ("pitch", "present", "present-brands")
_DECK_COOKIE = "halia_deck"
_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


def _deck_password() -> str:
    return _os.environ.get("HALIA_DECK_PASSWORD", "letsmakelotsofmoneythisyear")


def _deck_token() -> str:
    return _hashlib.sha256(("halia-deck:" + _deck_password()).encode("utf-8")).hexdigest()[:40]


def _deck_gate(path: str, wrong: bool = False) -> str:
    note = ('<p style="color:#b96a5a;font:500 13px Inter,system-ui,sans-serif;margin:0 0 14px">'
            "That password was declined. Try again.</p>") if wrong else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Private briefing &middot; Halia</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400&family=Inter:wght@400;500&display=swap" rel="stylesheet">
</head><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0b;color:#f4f1ea;font-family:Inter,system-ui,sans-serif">
<form method="post" action="{path}" style="text-align:center;padding:32px;max-width:420px">
  <div style="font:500 12px Inter,system-ui,sans-serif;letter-spacing:.32em;text-transform:uppercase;color:#d8d2c6;margin-bottom:22px">&#8258; Halia</div>
  <h1 style="font-family:'Cormorant Garamond',Georgia,serif;font-weight:300;font-size:clamp(30px,6vw,44px);margin:0 0 26px;line-height:1.05">This briefing is private.</h1>
  {note}
  <input type="password" name="pw" placeholder="Password" autofocus autocomplete="current-password"
    style="width:100%;box-sizing:border-box;background:#141416;border:1px solid rgba(255,255,255,.16);border-radius:999px;padding:14px 22px;color:#f4f1ea;font:500 15px Inter,system-ui,sans-serif;outline:none;text-align:center">
  <button style="margin-top:14px;width:100%;background:#d8d2c6;color:#141410;border:0;border-radius:999px;padding:14px 22px;font:600 14px Inter,system-ui,sans-serif;letter-spacing:.04em;cursor:pointer">Enter</button>
</form></body></html>"""


async def _deck_handler(request: Request) -> _HTML:
    path = request.url.path
    name = path.strip("/")
    if request.method == "POST":
        form = await request.form()
        if _hmac.compare_digest(str(form.get("pw") or ""), _deck_password()):
            resp = _Redirect(path, status_code=303)
            resp.set_cookie(_DECK_COOKIE, _deck_token(), max_age=86400 * 30, httponly=True,
                            samesite="lax", secure=request.url.scheme == "https")
            resp.headers.update(_NOINDEX)
            return resp
        return _HTML(_deck_gate(path, wrong=True), status_code=401, headers=_NOINDEX)
    if request.cookies.get(_DECK_COOKIE) != _deck_token():
        return _HTML(_deck_gate(path), headers=_NOINDEX)
    resp = _serve_page(name)
    resp.headers.update(_NOINDEX)
    return resp


for _name in _DECKS:
    app.add_api_route(f"/{_name}", _deck_handler, methods=["GET", "POST"],
                      include_in_schema=False, response_class=_HTML)


def _docs_handler(request: Request) -> _HTML:
    """Documentation is gated behind sign-in: only a merchant with a valid Halia
    session (or access link) can read the setup guides, so we don't hand our
    onboarding and product playbook to the public / competitors. Unauthenticated
    visitors get the same sign-in page as the dashboard.

    The page to serve is the request path itself (``/docs`` -> ``docs.html``,
    ``/docs/using-halia`` -> ``docs/using-halia.html``)."""
    from halia.api.tenant_auth import resolve_tenant
    from halia.api.onboarding import _signin_page
    if not resolve_tenant(request):
        return _HTML(_signin_page())
    return _serve_page(request.url.path.strip("/"))


# Documentation (web/site/docs.html + web/site/docs/<slug>.html) — sign-in gated.
for _docpath in ("docs", "docs/connect-your-store", "docs/crm-and-email", "docs/using-halia"):
    app.add_api_route(f"/{_docpath}", _docs_handler,
                      methods=["GET"], include_in_schema=False, response_class=_HTML)

# Per-industry solutions pages (web/site/solutions/<slug>.html — see scripts/build_solutions_pages.py).
for _ind in ("fashion", "wine", "beauty", "jewellery", "home", "gifting", "collectibles", "electronics"):
    app.add_api_route(f"/solutions/{_ind}", (lambda n: lambda: _serve_page(f"solutions/{n}"))(_ind),
                      methods=["GET"], include_in_schema=False, response_class=_HTML)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Public marketing origin (the haliascore.com front door — distinct from the app origin).
# Overridable so a staging deploy can advertise its own canonical host.
_SITE_ORIGIN = _os.environ.get("HALIA_SITE_URL", "https://haliascore.com").rstrip("/")

# Every publicly indexable route. Excludes the sign-in-gated docs and the
# noindex legal pages (which already carry X-Robots-Tag: noindex).
_INDEXABLE_PATHS = [
    "/", "/brand", "/clienteling", "/faq", "/pricing", "/responsible",
    "/security", "/solutions", "/demo", "/status",
] + [f"/solutions/{_i}" for _i in
     ("fashion", "wine", "beauty", "jewellery", "home", "gifting",
      "collectibles", "electronics")]


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    from fastapi.responses import PlainTextResponse
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /app\n"
        "Disallow: /console\n"
        "Disallow: /admin\n"
        "Disallow: /docs\n"
        f"\nSitemap: {_SITE_ORIGIN}/sitemap.xml\n"
    )
    return PlainTextResponse(body, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml():
    from fastapi.responses import Response
    urls = "".join(
        f"<url><loc>{_SITE_ORIGIN}{p}</loc></url>" for p in _INDEXABLE_PATHS
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return Response(xml, media_type="application/xml")


# Process start — used by the public status page to report uptime.
import datetime as _dt  # noqa: E402

_STARTED_MONO = _time.monotonic()
_STARTED_AT = _dt.datetime.now(_dt.timezone.utc)


def _fmt_uptime(secs: float) -> str:
    secs = int(secs)
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s" if m else f"{s}s"


def system_status() -> dict:
    """Health snapshot: uptime + component checks. No customer data — subsystem liveness only.

    Each check is 'operational' or 'degraded'. Shared by the public status page (/status.json)
    and the authenticated console dashboard (/console) so both read one source of truth.
    """
    checks = []

    # Web: if this handler runs, the API is serving.
    checks.append({"key": "api", "name": "API & dashboard", "status": "operational",
                   "note": "Serving requests"})

    # Persistence (encrypted merchant secrets only — no customer rows here).
    db_status, db_note = "operational", "Reachable"
    backend = "database"
    try:
        store = shop_store()
        store._run("SELECT 1", fetch="one")
        backend = "PostgreSQL" if getattr(store, "pg", False) else "SQLite"
        db_note = "Reachable"
    except Exception:
        db_status, db_note = "degraded", "Unreachable"
    checks.append({"key": "db", "name": f"Secret store ({backend})", "status": db_status,
                   "note": db_note})

    # Scoring engine importable/ready.
    eng_status, eng_note = "operational", "Ready"
    try:
        from scoring.combine import active_signals
        eng_note = f"{len(active_signals(include_origin=False))} signals active"
    except Exception:
        eng_status, eng_note = "degraded", "Unavailable"
    checks.append({"key": "engine", "name": "Scoring engine", "status": eng_status,
                   "note": eng_note})

    # In-memory scoring cache (zero-retention working set).
    cache_status, cache_note = "operational", "Zero-retention (in memory)"
    try:
        from halia import cache as _cache
        ttl = int(getattr(_cache, "TTL_SECONDS", _os.environ.get("HALIA_CACHE_TTL", 300)) or 300)
        cache_note = f"TTL {ttl}s · results discarded after"
    except Exception:
        cache_status, cache_note = "degraded", "Unavailable"
    checks.append({"key": "cache", "name": "In-memory scoring cache", "status": cache_status,
                   "note": cache_note})

    overall = "operational" if all(c["status"] == "operational" for c in checks) else "degraded"
    uptime = _time.monotonic() - _STARTED_MONO
    return {
        "status": overall,
        "started_at": _STARTED_AT.isoformat(timespec="seconds"),
        "uptime_seconds": int(uptime),
        "uptime_human": _fmt_uptime(uptime),
        "now": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "host": "Render",
        "checks": checks,
    }


@app.get("/status.json", include_in_schema=False)
def status_json() -> dict:
    """Public health snapshot for the status page (delegates to ``system_status``)."""
    return system_status()


@app.post("/subscribe", include_in_schema=False)
def subscribe(payload: Any = Body(...)) -> dict:
    """Marketing-site email capture. Stores the email; demo requests also start the Brevo journey."""
    from halia.api.shopify_auth import shop_store

    email = str((payload or {}).get("email", "")).strip().lower()
    if "@" not in email or "." not in email.split("@")[-1] or len(email) > 200:
        raise HTTPException(422, "Enter a valid email address.")
    shop_store().add_subscriber(email)
    # A demo request (source=demo) is added to the Brevo Demo list, which fires the demo-nurture
    # automation ("we'll be in touch" + the 3-email drip). Best-effort; never blocks the response.
    if str((payload or {}).get("source", "")).lower() == "demo":
        import halia.notify_brevo as notify_brevo
        notify_brevo.add_demo_lead(email)          # record on the Brevo Demo list
        try:
            from halia import journeys
            journeys.enroll_demo(email)            # start the Halia-sent demo nurture
        except Exception:  # noqa: BLE001
            pass
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

    def _safe(v):
        """Defuse CSV/formula injection: a customer-controlled cell starting with = + - @ (or a
        control char) can execute when the merchant opens the file in Excel/Sheets. Prefix it with
        an apostrophe so the spreadsheet treats it as text. Numbers pass through unchanged."""
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Email", "Phone", "Location", "Grade", "Score", "Current spend",
                "Latent value", "Signal count", "Signals", "Recommended approach"])
    for c in rows:
        signals = "; ".join(s.get("d", "") for s in (c.get("signals") or []))
        w.writerow([_safe(c.get("name", "")), _safe(c.get("email", "")), _safe(c.get("phone", "")),
                    _safe(c.get("loc", "")), c.get("grade", ""), c.get("score", ""),
                    c.get("spend", ""), c.get("latent", ""),
                    c.get("count", len(c.get("signals") or [])), _safe(signals), _safe(c.get("reco", ""))])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=halia-hidden-vics.csv"})


# ── POS UI extension: fast single-customer lookup for the at-the-till tile ──────────
def _pos_payload(r) -> dict:
    """Compact, staff-facing shape for the POS tile — derived from a ScoreResult."""
    return {"matched": bool(getattr(r, "matched", True)),
            "vic": bool(r.hidden_vic or r.is_priority),
            "grade": r.grade, "score": r.score, "tier": r.tier,
            "is_priority": bool(r.is_priority), "hidden_vic": bool(r.hidden_vic),
            "gesture": r.gesture, "signals": (r.signals or [])[:3],
            "reasons": r.reasons, "spend": r.spend}


def _pos_match_cached(entry: dict, customer_id, email):
    """Find an already-scored customer in RAM (never triggers a full-shop sync)."""
    if customer_id:
        num = str(customer_id).rsplit("/", 1)[-1]  # POS numeric id vs stored gid form
        for cid in (customer_id, num, f"gid://shopify/Customer/{num}"):
            r = data.result_by_id(entry, cid)
            if r:
                return r
    if email:
        return data.result_by_email(entry, email)
    return None


def _pos_live(shop: str, customer_id, email):
    """Score just this one customer live (single-customer fetch, not a full sync)."""
    from halia.api.settings import settings_for
    from halia.schema import ScoreResult
    from scoring.combine import score_customers
    from scoring.shopify import orders_to_customers
    from scoring.shopify_fetch import fetch_customer_orders, http_transport

    token = shop_store().get_token(shop)
    if not token:
        return None
    by, ident = ("id", customer_id) if customer_id else ("email", email)
    orders = fetch_customer_orders(ident, transport=http_transport(shop, token), by=by)
    if not orders:
        return None
    customers = orders_to_customers(orders).rename(columns={"orders_count": "Count of CUST_ID"})
    if customers.empty:
        return None
    s = settings_for(shop)
    scored = score_customers(customers, weights=s.get("signal_weights"),
                             vic_threshold=s["vic_threshold"],
                             include_origin=data._include_origin(shop))
    return ScoreResult.from_scored_row(scored.iloc[0])


@app.get("/v1/pos/score")
def pos_score(shop: str = Depends(require_shop),
              customer_id: Optional[str] = Query(None),
              email: Optional[str] = Query(None)) -> dict:
    """The at-the-till lookup for the POS tile: warm RAM cache first, and on a miss
    score just this one customer live — never a full-shop sync while a client waits."""
    from halia.cache import cache

    if not customer_id and not email:
        raise HTTPException(422, "Provide ?customer_id= or ?email=")
    data.record_activity(shop, "pos_lookup")  # at-the-till usage, for the console dashboard
    entry = cache.get(shop)  # warm path only — do NOT call results_for (it would full-sync)
    r = _pos_match_cached(entry, customer_id, email) if entry else None
    if r is None:
        r = _pos_live(shop, customer_id, email)
    if r is None or not getattr(r, "matched", True):
        return {"matched": False}
    return _pos_payload(r)


# Mount the embedded entry, self-service onboarding, Klaviyo + Shopify write-back, fulfilment
# view, and compliance webhooks.
from halia.api import (  # noqa: E402
    billing, blog, board, catalog, content, embedded, endear_integration, feedback, fulfilment,
    hubspot_integration, integrations, lifecycle, mailchimp_integration, onboarding, console,
    realtime, settings, shopify_push, shopify_segments, slack_integration, webhooks,
)

embedded.register(app)
content.register(app)
blog.register(app)
catalog.register(app)
board.register(app)
console.register(app)
onboarding.register(app)
integrations.register(app)
mailchimp_integration.register(app)
hubspot_integration.register(app)
endear_integration.register(app)
slack_integration.register(app)
shopify_segments.register(app)
realtime.register(app)
settings.register(app)
fulfilment.register(app)
webhooks.register(app)
billing.register(app)
lifecycle.register(app)
shopify_push.register(app)
feedback.register(app)
