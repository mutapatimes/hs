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
