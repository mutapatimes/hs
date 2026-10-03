"""The embedded entry must never block the install navigation on a full fetch + score (the
review store hit a 502 that way). First load kicks a background sync and renders the scoring
screen; the SPA polls /v1/sync/state and reloads when the book is ready."""
from fastapi.testclient import TestClient

from halia.api import embedded, onboarding, shopify_auth
from halia.api.app import app
from halia.cache import cache

SHOP = "review-store.myshopify.com"


def _client(monkeypatch):
    """The embedded entry authenticates with an App Bridge session token (?id_token=), not the
    hosted cookie; stand in for Shopify's signed JWT."""
    monkeypatch.setattr(embedded, "verify_session_token", lambda tok: SHOP)
    monkeypatch.setattr(shopify_auth, "verify_session_token", lambda tok: SHOP)
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-session-token"})
    return c


def test_first_load_renders_scoring_screen_without_inline_sync(monkeypatch):
    cache.clear()
    kicked, exchanged = [], []
    monkeypatch.setattr(shopify_auth, "ensure_offline_token",
                        lambda shop, tok, force=False: exchanged.append(shop) or "offline-token")
    monkeypatch.setattr(onboarding, "_start_sync", lambda shop, notify=False: kicked.append(shop))
    # if anything tried the old inline path it would explode here
    monkeypatch.setattr(embedded.data, "sync_shop_authed",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("inline sync ran")))

    r = _client(monkeypatch).get("/")
    assert r.status_code == 200
    assert "const SYNC_RUNNING = true;" in r.text
    assert exchanged == [SHOP] and kicked == [SHOP]
    assert "Content-Security-Policy" in r.headers


def test_sync_state_reports_progress(monkeypatch):
    cache.clear()
    monkeypatch.setattr(onboarding, "sync_status",
                        lambda shop: {"state": "running", "error": "", "ts": 0})
    d = _client(monkeypatch).get("/v1/sync/state").json()
    assert d == {"state": "running", "error": "", "ready": False}


def test_warm_cache_renders_the_real_dashboard(monkeypatch):
    cache.clear()
    payload = dict(embedded._pending_payload()); payload.pop("sync_running")
    payload["data"] = [{"cid": "c1", "name": "Grace", "grade": "A*", "score": 90}]
    cache.set(SHOP, results=[], payload=payload, orders=[])
    monkeypatch.setattr(onboarding, "_start_sync",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("sync kicked on a warm cache")))
    r = _client(monkeypatch).get("/")
    assert r.status_code == 200 and "const SYNC_RUNNING = false;" in r.text
    cache.clear()


def test_an_admin_frame_load_without_a_usable_token_is_framed_not_refused(monkeypatch):
    """Inside the Shopify admin with no token we can verify, the answer must still be a page the
    admin may frame: first a bootstrap that asks App Bridge for a token, then, with a token that
    still fails, the reason in a sentence. Never the marketing page, which forbids framing."""
    from fastapi.testclient import TestClient
    from halia.api.app import app
    c = TestClient(app)
    base = "/?shop=htown-store.myshopify.com&host=YWRtaW4&embedded=1"
    r = c.get(base)
    assert r.status_code == 200
    assert "frame-ancestors https://htown-store.myshopify.com https://admin.shopify.com" in r.headers["content-security-policy"]
    assert "shopify.idToken()" in r.text
    r2 = c.get(base + "&id_token=not.a.token&retried=1")
    assert r2.status_code == 200
    assert "admin.shopify.com" in r2.headers["content-security-policy"]
    assert "Couldn't load your scores" in r2.text and "Invalid session token" in r2.text
    # A made-up shop never reaches the frame policy.
    r3 = c.get("/?shop=evil.example.com&embedded=1")
    assert "frame-ancestors 'none'" in r3.headers["content-security-policy"]
