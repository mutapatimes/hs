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
    # A stale token in the address (the scoring screen's reload, minutes later) is refreshed too.
    r1 = c.get(base + "&id_token=stale.token.here")
    assert r1.status_code == 200 and "shopify.idToken()" in r1.text
    r2 = c.get(base + "&id_token=not.a.token&retried=1")
    assert r2.status_code == 200
    assert "admin.shopify.com" in r2.headers["content-security-policy"]
    assert "Couldn't load your scores" in r2.text and "Invalid session token" in r2.text
    # A made-up shop never reaches the frame policy.
    r3 = c.get("/?shop=evil.example.com&embedded=1")
    assert "frame-ancestors 'none'" in r3.headers["content-security-policy"]


def test_sync_state_restarts_a_run_lost_to_a_restart(monkeypatch):
    """The scoring screen polls /v1/sync/state. After a deploy mid-run the status is gone and the
    book is not in memory; the poll must start a fresh run rather than answer idle for ever."""
    from halia.api import embedded as emb
    import halia.api.onboarding as ob
    client = _client(monkeypatch)
    started = []
    monkeypatch.setattr(ob, "_start_sync", lambda s, notify=False: started.append(s))
    monkeypatch.setattr(ob, "sync_status", lambda s: {"state": "idle", "error": "", "ts": 0})
    monkeypatch.setattr(emb.cache, "get", lambda s: None)
    r = client.get("/v1/sync/state", params={"id_token": "t"})
    assert r.status_code == 200 and r.json()["ready"] is False
    assert started == [SHOP]
    # With the book in memory nothing is started: the page reloads into the dashboard.
    monkeypatch.setattr(emb.cache, "get", lambda s: {"payload": {}})
    started.clear()
    client.get("/v1/sync/state", params={"id_token": "t"})
    assert started == []


def test_a_stale_book_is_served_at_once_and_refreshed_behind_the_page(monkeypatch):
    """Past its freshness the book stays in memory. The embedded entry shows it immediately and
    starts a pull in the background, instead of sending the merchant back to the scoring screen
    for the whole of a large store's pull."""
    from halia.api import embedded as emb
    import halia.api.onboarding as ob
    from halia.cache import ResultsCache
    client = _client(monkeypatch)
    c = ResultsCache(ttl=0, idle=3600)                       # everything is stale the moment it lands
    c.set(SHOP, [], {"data": [{"name": "x"}], "segments": {}, "orders": [], "landscape": {},
                      "platform": "shopify", "stat_scored": "1", "stat_latent": "", "stat_count": "1",
                      "stat_avgspend": "", "stat_toptier": "", "full_history": True, "masked": False,
                      "locked_count": 0, "locked_latent": "", "sync_running": False, "order_window": None,
                      "sync_diag": {}, "order_cap": {}}, {})
    monkeypatch.setattr(emb, "cache", c)
    started = []
    monkeypatch.setattr(ob, "_start_sync", lambda s, notify=False: started.append(s))
    r = client.get("/", params={"id_token": "t"})
    assert r.status_code == 200
    assert "Scoring your customers" not in r.text or "SYNC_RUNNING=false" in r.text.replace(" ", "")
    assert started == [SHOP]                                   # the refresh runs behind the page
    assert c.get(SHOP) is None and c.get_stale(SHOP) is not None


def test_recently_opened_stores_are_warmed_when_their_book_is_not_in_memory(monkeypatch, tmp_path):
    """After a restart the cache is empty. The warm-up scores the stores opened in the last day
    and the newly installed ones, and leaves alone a store whose book is already fresh."""
    import halia.api.onboarding as ob
    from halia.cache import ResultsCache
    from halia.store import ShopStore
    st = ShopStore(db_path=tmp_path / "w.db")
    st.save_shop("fresh.myshopify.com", "tok"); st.touch_shop_open("fresh.myshopify.com")
    st.save_shop("cold.myshopify.com", "tok"); st.touch_shop_open("cold.myshopify.com")
    st.save_shop("new.myshopify.com", "tok")                       # installed today, never opened
    st.save_shop("old.myshopify.com", "tok")
    st._run("UPDATE shops SET installed_at = '2020-01-01T00:00:00+00:00' WHERE shop = 'old.myshopify.com'")
    assert set(st.recently_opened_shops()) == {"fresh.myshopify.com", "cold.myshopify.com", "new.myshopify.com"}
    c = ResultsCache(ttl=3600)
    c.set("fresh.myshopify.com", [], {"data": []}, {})
    monkeypatch.setattr("halia.api.shopify_auth.shop_store", lambda: st)
    monkeypatch.setattr("halia.cache.cache", c)
    started = []
    monkeypatch.setattr(ob, "_start_sync", lambda s, notify=False: started.append(s))
    out = ob.warm_books()
    assert sorted(out["warmed"]) == sorted(started) == ["cold.myshopify.com", "new.myshopify.com"]
