"""FastAPI surface: stateless score + shop-scoped reads from the RAM cache (no DB)."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia.api.app import app
from halia.cache import cache
from halia.schema import ScoreResult

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _token(secret=SECRET, aud=KEY, dest=f"https://{SHOP}"):
    return jwt.encode({"iss": f"https://{SHOP}/admin", "dest": dest, "aud": aud, "sub": "1",
                       "exp": int(time.time()) + 3600}, secret, algorithm="HS256")


def _vic():
    return ScoreResult(matched=True, flagged=True, tier="A1", grade="A*", score=99,
                       is_priority=True, signal_count=2, signals=["Work email"],
                       reasons="Work email: GS", gesture="coffee", spend=400.0,
                       hidden_vic=True, customer_id="c1", email="vic@x.com", phone=None)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    cache.clear()
    cache.set(SHOP, results=[_vic()], payload={},
              orders=[{"order_id": "o1", "created_at": "2026-06-01", "customer_id": "c1",
                       "email": "vic@x.com"}])
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {_token()}"})
    yield c
    cache.clear()


def test_health_is_open(client):
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_status_json_is_open_and_reports_components(client):
    r = TestClient(app).get("/status.json")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] in {"operational", "degraded"}
    assert d["host"] == "Render"
    assert "uptime_human" in d and d["uptime_seconds"] >= 0
    keys = {c["key"] for c in d["checks"]}
    assert {"api", "db", "engine", "cache"} <= keys


def test_status_page_serves(client):
    assert TestClient(app).get("/status").status_code == 200


def test_robots_txt_serves_and_points_to_sitemap():
    r = TestClient(app).get("/robots.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "Sitemap: https://haliascore.com/sitemap.xml" in r.text
    assert "Disallow: /admin" in r.text


def test_sitemap_lists_public_pages_only():
    r = TestClient(app).get("/sitemap.xml")
    assert r.status_code == 200 and "xml" in r.headers["content-type"]
    body = r.text
    for path in ("/", "/pricing", "/security", "/solutions/fashion",
                 "/docs", "/docs/connect-your-store", "/docs/crm-and-email"):
        assert f"<loc>https://haliascore.com{path}</loc>" in body
    # gated / noindex routes must never be advertised for crawling
    assert "/docs/using-halia" not in body and "/admin" not in body and "/privacy" not in body


@pytest.mark.parametrize("path", [
    "/", "/brand", "/clienteling", "/faq", "/pricing", "/responsible",
    "/security", "/solutions", "/demo", "/status",
    "/solutions/fashion", "/solutions/wine", "/solutions/beauty",
    "/solutions/jewellery", "/solutions/home", "/solutions/gifting",
    "/solutions/collectibles", "/solutions/electronics",
])
def test_public_pages_carry_social_meta(path):
    html = TestClient(app).get(path).text
    assert 'rel="canonical"' in html
    assert 'name="twitter:card" content="summary_large_image"' in html
    assert 'property="og:title"' in html and 'property="og:image"' in html
    # canonical must be absolute on the production origin
    assert "https://haliascore.com" in html


def test_embedded_section_routes_are_wired():
    """The admin sidebar deep-links (/view/<section>) must resolve to the dashboard handler, not
    404. Unauthenticated they fall back to the same marketing surface as "/" — that's enough to
    prove the route exists and delegates (a missing route would 404)."""
    c = TestClient(app)
    assert c.get("/").status_code == 200
    for path in ("/view/clients", "/view/catalogues", "/view/pipeline",
                 "/view/orders", "/view/map", "/view/settings"):
        assert c.get(path).status_code == 200, path


def test_delete_account_wipes_and_signs_out(client):
    # Precondition: the tenant has cached results and can read them.
    assert client.get("/v1/hidden-vics", params={"limit": 5}).status_code == 200
    r = client.post("/v1/account/delete")
    assert r.status_code == 200 and r.json() == {"ok": True}
    # Session cookies are cleared on the way out.
    assert "halia_s" in r.headers.get("set-cookie", "")
    # Everything held for the shop is gone: the RAM cache is evicted, reads 404.
    assert cache.get(SHOP) is None
    assert client.get("/v1/hidden-vics").status_code == 404


def test_delete_account_requires_auth():
    from fastapi.testclient import TestClient as _TC
    assert _TC(app).post("/v1/account/delete").status_code == 401


def test_post_score_is_stateless_and_open(client):
    r = TestClient(app).post("/v1/score", json={
        "CUST_ID": "x", "Name": "Sir A B", "EMAIL_ADDR": "a@gs.com",
        "LATEST_BILLING_ZIP": "SW1X 7XL", "LATEST_BILLING_ADDRESS4": "United Kingdom",
        "Spent": 400})
    assert r.status_code == 200 and r.json()["grade"] == "A*"


def test_reads_require_session_token(client):
    assert TestClient(app).get("/v1/hidden-vics").status_code == 401


def test_shop_scoped_reads_from_cache(client):
    assert client.get("/v1/score", params={"id": "c1"}).json()["grade"] == "A*"
    assert client.get("/v1/score", params={"email": "vic@x.com"}).json()["customer_id"] == "c1"
    assert client.get("/v1/orders/o1/score").json()["grade"] == "A*"
    hv = client.get("/v1/hidden-vics", params={"limit": 5}).json()
    assert len(hv) == 1 and hv[0]["customer_id"] == "c1"


def test_other_shop_sees_nothing(client):
    other = jwt.encode({"iss": "https://rival.myshopify.com/admin",
                        "dest": "https://rival.myshopify.com", "aud": KEY, "sub": "1",
                        "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    # rival has no cache entry and no stored token -> results_for returns None -> 404
    r = TestClient(app).get("/v1/hidden-vics", headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 404


def test_fulfilment_view_renders(client):
    html = client.get("/fulfilment").text
    assert "Fulfilment pick list" in html and "coffee" in html


def test_embedded_home_without_token_serves_marketing_site():
    # A public visitor (no Shopify session token) gets the marketing site, not the app.
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "Connect your store" in r.text and "Halia" in r.text


def test_docs_public_guides_open_but_playbook_gated():
    # The connection guides (store, email/CRM) are public — they aid discovery and reveal no
    # scoring internals. The product playbook (using-halia) stays gated; a logged-out visitor
    # gets the sign-in page instead, and only a signed-in merchant sees it.
    from halia.api.tenant_auth import make_session, SESSION_COOKIE

    out = TestClient(app)
    assert "Up and running" in out.get("/docs").text                    # docs hub, public
    assert "What happens next" in out.get("/docs/connect-your-store").text  # guide, public
    gated = out.get("/docs/using-halia")
    assert gated.status_code == 200
    assert "weekly rhythm" not in gated.text                            # the real guide is withheld

    signed_in = TestClient(app, cookies={SESSION_COOKIE: make_session("demo.myshopify.com")})
    assert "weekly rhythm" in signed_in.get("/docs/using-halia").text
