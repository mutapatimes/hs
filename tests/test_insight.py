"""The dashboard's AI conveniences: written client summary + plain-English filtering.

Both endpoints follow the same rule as the rest of the engine — the model proposes, deterministic
code decides. The tests that matter most are the ones proving the second half: a filter value the
page cannot apply is dropped rather than passed through, and neither endpoint invents a client.
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia.api import insight
from halia.api.app import app
from halia.cache import cache
from halia.store import ShopStore

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    store = ShopStore(db_path=tmp_path / "i.db")
    monkeypatch.setattr("halia.api.shopify_auth._shop_store", store)
    cache.clear()
    yield TestClient(app), store
    cache.clear()


def _seed(**kw):
    row = {"cid": "c1", "name": "Grace Ladoja", "grade": "A*", "tier": "A1", "known": False,
           "latent": "£12,400", "spend": 4200, "ordersCount": 3, "last": "Mar 2026",
           "band": "lapsed", "signals": [{"seg": "work", "d": "Work email: Goldman Sachs"}]}
    row.update(kw)
    cache.set(SHOP, results=[], payload={"data": [row]}, orders=[])


# ── client summary ────────────────────────────────────────────────────────────
def test_summary_is_silent_without_an_ai_key(client, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    c, _ = client
    _seed()
    d = c.post("/v1/client/summary", headers=_auth(), json={"cid": "c1"}).json()
    assert d["summary"] == "" and d["ai_available"] is False


def test_summary_is_written_from_the_engines_own_evidence(client, monkeypatch):
    from halia import llm
    seen = {}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete",
                        lambda s, u, **k: seen.update(user=u) or "Quietly wealthy, and gone quiet.")
    c, _ = client
    _seed()
    d = c.post("/v1/client/summary", headers=_auth(), json={"cid": "c1"}).json()
    assert d["source"] == "ai" and d["summary"] == "Quietly wealthy, and gone quiet."
    assert "Goldman Sachs" in seen["user"] and "£12,400" in seen["user"]


def test_summary_is_memoised_for_the_life_of_the_book(client, monkeypatch):
    """Opening the same drawer repeatedly must cost one call per client, not one per click."""
    from halia import llm
    calls = {"n": 0}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or "x")
    c, _ = client
    _seed()
    first = c.post("/v1/client/summary", headers=_auth(), json={"cid": "c1"}).json()
    again = c.post("/v1/client/summary", headers=_auth(), json={"cid": "c1"}).json()
    assert calls["n"] == 1
    assert first["source"] == "ai" and again["source"] == "cache"
    assert again["summary"] == "x"


def test_summary_forgets_when_the_book_does(client, monkeypatch):
    """The memo lives inside the shop's cache entry, so eviction takes it too — the zero-retention
    story has to hold for anything written about a client, not just the client."""
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "x")
    c, _ = client
    _seed()
    c.post("/v1/client/summary", headers=_auth(), json={"cid": "c1"})
    cache.evict(SHOP)
    assert cache.get_note(SHOP, "summary:c1") is None


def test_summary_needs_a_cid(client):
    c, _ = client
    assert c.post("/v1/client/summary", headers=_auth(), json={}).status_code == 422


def test_summary_on_an_unknown_client_says_nothing(client, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "should not be reached")
    c, _ = client
    _seed()
    d = c.post("/v1/client/summary", headers=_auth(), json={"cid": "nobody"}).json()
    assert d["summary"] == ""


# ── plain-English filtering ───────────────────────────────────────────────────
_FILTER = {"grade": "A", "play": "sleeping", "city": "London", "segments": ["work"],
           "minSignals": 2, "sort": "latent", "query": "", "explain": "Quiet A clients in London."}


def test_query_returns_the_pages_own_filter_values(client, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: dict(_FILTER))
    c, _ = client
    d = c.post("/v1/clients/query", headers=_auth(),
               json={"q": "quiet A clients in London", "cities": ["London", "Paris"],
                     "segments": ["work", "property"]}).json()
    assert d["ok"] is True
    assert d["filter"]["grade"] == "A" and d["filter"]["city"] == "London"
    assert d["filter"]["segments"] == ["work"] and d["filter"]["play"] == "sleeping"
    assert d["filter"]["explain"] == "Quiet A clients in London."


def test_a_value_the_page_cannot_apply_is_dropped(client, monkeypatch):
    """The line between a suggestion and an instruction: an invented city or segment must not
    reach the list, or the user gets an empty view they cannot account for."""
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: dict(
        _FILTER, city="Atlantis", segments=["work", "astrology"], grade="A++", sort="vibes"))
    c, _ = client
    d = c.post("/v1/clients/query", headers=_auth(),
               json={"q": "x", "cities": ["London"], "segments": ["work"]}).json()
    f = d["filter"]
    assert f["city"] == "all"          # Atlantis is not a city this book has
    assert f["segments"] == ["work"]   # astrology is not a signal this engine has
    assert f["grade"] == "all"         # A++ is not a grade
    assert f["sort"] == "score"        # vibes is not a sort


def test_min_signals_is_clamped(client, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: dict(_FILTER, minSignals=99))
    c, _ = client
    d = c.post("/v1/clients/query", headers=_auth(), json={"q": "x"}).json()
    assert d["filter"]["minSignals"] == 5


def test_query_is_off_without_an_ai_key(client, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    c, _ = client
    d = c.post("/v1/clients/query", headers=_auth(), json={"q": "x"}).json()
    assert d["ok"] is False and d["reason"] == "no-ai"


def test_query_needs_a_question(client):
    c, _ = client
    assert c.post("/v1/clients/query", headers=_auth(), json={"q": "  "}).status_code == 422


def test_query_failure_is_reported_not_guessed(client, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: None)
    c, _ = client
    d = c.post("/v1/clients/query", headers=_auth(), json={"q": "x"}).json()
    assert d["ok"] is False and d["reason"] == "failed"


def test_clean_filter_defaults_everything_it_cannot_read():
    out = insight._clean_filter({}, [], [])
    assert out == {"grade": "all", "play": "", "city": "all", "segments": [], "minSignals": 0,
                   "sort": "score", "query": "", "explain": ""}
