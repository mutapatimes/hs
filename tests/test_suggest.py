"""Suggesting products for one client, and the bespoke catalogue link.

The property that matters is the same one the rest of the engine keeps: the model proposes, the
server decides. It may only choose ids out of a shortlist the server built from the merchant's own
products, and anything it returns that is not in that shortlist is dropped — so it cannot put a
product, a price or a link in front of a client that does not exist. The other property is that a
bespoke catalogue writes nothing: the selection lives in the link, as the recipient's name already
does everywhere else.
"""
import pytest
from fastapi.testclient import TestClient

from halia.api import catalog, extension, onboarding, shopify_auth
from halia.api.app import app
from halia.api.data import _history, bought_titles
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "shopx"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Shop X", hash_token(tok))
    cache.clear()
    yield TestClient(app), store, tok
    cache.clear()
    catalog._PRODUCT_CACHE.clear()


def _ext(client, tok):
    return client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]


def _products(n=4):
    return [{"id": str(100 + i), "title": f"Tan wool coat {i}", "type": "Outerwear",
             "vendor": "House", "price": str(900 + i * 100), "currency": "£",
             "tags": ["wool"], "image_url": f"https://x/{i}.jpg", "status": "ACTIVE"}
            for i in range(n)]


def _seed_client():
    cache.set(SHOP, results=[], payload={"data": [{
        "cid": "c1", "name": "Grace Ladoja", "email": "grace@x.com", "grade": "A*", "tier": "A1",
        "known": False, "spend": 4200, "ordersCount": 2, "band": "lapsed",
        "signals": [{"seg": "work", "d": "Work email: Goldman Sachs"}],
        "orders": [{"date": "2026-06-01", "amount": 2400, "items": 1, "titles": ["Camel scarf"]}],
    }]}, orders=[])


# ── what the client has bought now survives the sync ──────────────────────────
def test_history_carries_the_products_not_just_the_count():
    orders = [{"customer": {"id": 1}, "created_at": "2026-06-01", "total_price": "1200",
               "line_items": [{"quantity": 1, "title": "Tan wool coat"},
                              {"quantity": 2, "title": "Camel scarf"}]}]
    row = _history(orders)["1"][0]
    assert row["items"] == 3                       # the count still works
    assert row["titles"] == ["Camel scarf", "Tan wool coat"]


def test_bought_titles_are_distinct_newest_first_and_capped():
    rows = [{"titles": ["Coat"]}, {"titles": ["Coat", "Scarf"]},
            {"titles": [f"P{i}" for i in range(20)]}]
    got = bought_titles(rows)
    assert got[:2] == ["Coat", "Scarf"] and len(got) == 12 and len(set(got)) == 12


def test_orders_without_line_items_carry_no_titles():
    orders = [{"customer": {"id": 1}, "created_at": "2026-06-01", "total_price": "10"}]
    assert "titles" not in _history(orders)["1"][0]


# ── the shortlist is deterministic, and bounds what the model ever sees ───────
def test_shortlist_caps_the_corpus():
    prods = [{"id": str(i), "title": f"Item {i}", "price": "500"} for i in range(900)]
    assert len(extension._shortlist(prods, [], 500.0)) == extension._CORPUS_CAP


def test_a_small_catalogue_is_passed_through_whole():
    prods = _products(4)
    assert extension._shortlist(prods, [], 0.0) == prods


def test_shortlist_prefers_what_they_already_buy():
    prods = ([{"id": "keep", "title": "Cashmere scarf", "price": "300", "tags": []}]
             + [{"id": str(i), "title": "Rubber boot", "price": "300", "tags": []}
                for i in range(400)])
    top = extension._shortlist(prods, ["Camel cashmere scarf"], 300.0)[0]
    assert top["id"] == "keep"


# ── suggest ───────────────────────────────────────────────────────────────────
def test_suggest_returns_only_products_that_exist(env, monkeypatch):
    """The guarantee: an id the model invents never reaches the associate."""
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: _products(3))
    monkeypatch.setattr(extension, "_variant_of", lambda shop, title: {"id": "v9"})
    monkeypatch.setattr(llm, "structured", lambda *a, **k: {"picks": [
        {"id": "100", "why": "She asked about this."},
        {"id": "does-not-exist", "why": "Invented."},
    ]})
    client, store, tok = env
    _seed_client()
    d = client.post("/v1/extension/suggest", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": _ext(client, tok)}).json()
    assert [p["product_id"] for p in d["picks"]] == ["100"]
    assert d["picks"][0]["variant_id"] == "v9" and d["picks"][0]["why"] == "She asked about this."
    assert store.shop_metric(SHOP, "extension_suggest_ai") == 1


def test_suggest_sees_the_clients_standing_and_purchases(env, monkeypatch):
    from halia import llm
    seen = {}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: _products(3))
    monkeypatch.setattr(extension, "_variant_of", lambda shop, title: None)
    monkeypatch.setattr(llm, "structured",
                        lambda s, u, sc, **k: seen.update(user=u) or {"picks": []})
    client, store, tok = env
    _seed_client()
    client.post("/v1/extension/suggest",
                json={"email": "grace@x.com", "thread": [{"from": "them", "text": "a tan coat?"}]},
                headers={"X-Halia-Ext-Token": _ext(client, tok)})
    assert "Camel scarf" in seen["user"]            # what they bought
    assert "Goldman Sachs" in seen["user"]          # why they matter
    assert "tan coat" in seen["user"]               # what they just asked for
    assert "100 | Tan wool coat 0" in seen["user"]  # the shortlist, with ids


def test_a_product_without_a_buyable_variant_is_still_offered(env, monkeypatch):
    """It can't go in a cart, but it can go in a catalogue."""
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: _products(2))
    monkeypatch.setattr(extension, "_variant_of", lambda shop, title: None)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: {"picks": [{"id": "100", "why": "x"}]})
    client, store, tok = env
    _seed_client()
    d = client.post("/v1/extension/suggest", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": _ext(client, tok)}).json()
    assert d["picks"][0]["variant_id"] is None and d["picks"][0]["product_id"] == "100"


def test_suggest_is_silent_without_a_model(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    _seed_client()
    d = client.post("/v1/extension/suggest", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": _ext(client, tok)}).json()
    assert d["picks"] == [] and d["ai_available"] is False


def test_suggest_respects_the_weekly_cap(env, monkeypatch):
    from halia import llm
    called = {"n": 0}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {"picks": []})
    monkeypatch.setattr(extension.config, "LLM_WEEKLY_CAP", 1)
    client, store, tok = env
    store.bump_metric(SHOP, "extension_suggest_ai", 1)
    _seed_client()
    d = client.post("/v1/extension/suggest", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": _ext(client, tok)}).json()
    assert d["picks"] == [] and called["n"] == 0


def test_suggest_needs_a_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/suggest", json={}).status_code == 401


# ── the bespoke catalogue link ────────────────────────────────────────────────
def test_catalogue_link_is_signed_and_carries_the_selection(env):
    client, store, tok = env
    d = client.post("/v1/extension/catalogue",
                    json={"product_ids": ["100", "101"], "name": "Grace Ladoja"},
                    headers={"X-Halia-Ext-Token": _ext(client, tok)}).json()
    assert "/for?" in d["url"] and "p=100%2C101" in d["url"] and "to=Grace" in d["url"]
    assert "s=" in d["url"]


def test_catalogue_link_needs_products(env):
    client, store, tok = env
    r = client.post("/v1/extension/catalogue", json={"product_ids": []},
                    headers={"X-Halia-Ext-Token": _ext(client, tok)})
    assert r.status_code == 422


def test_the_signature_is_bound_to_the_shop_and_the_selection():
    a = catalog.adhoc_sig("shop-a", "1,2")
    assert a == catalog.adhoc_sig("shop-a", "1,2")
    assert a != catalog.adhoc_sig("shop-b", "1,2")     # another tenant cannot reuse it
    assert a != catalog.adhoc_sig("shop-a", "1,3")     # nor can the selection be edited


def test_an_unsigned_or_tampered_link_is_refused(env, monkeypatch):
    client, store, tok = env
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: _products(3))
    assert client.get(f"/catalog/for?sh={SHOP}&p=100").status_code == 403
    assert client.get(f"/catalog/for?sh={SHOP}&p=100&s=nonsense").status_code == 403
    good = catalog.adhoc_sig(SHOP, "100")
    assert client.get(f"/catalog/for?sh={SHOP}&p=101&s={good}").status_code == 403


def test_a_tenant_row_does_not_break_catalogue_rendering(env, monkeypatch):
    """Regression: the store hands back a sqlite3.Row, which has no .get, so _shop_display and the
    product-fetch dispatch both raised for any tenant that actually had a row. It stayed hidden
    because no catalogue test created one."""
    client, store, tok = env
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: _products(2))
    assert catalog._shop_display(SHOP) == "Shop X"          # the tenant's label, not a crash
    sig = catalog.adhoc_sig(SHOP, "100")
    assert client.get(f"/catalog/for?sh={SHOP}&p=100&s={sig}").status_code == 200


def test_a_bespoke_catalogue_renders_and_stores_nothing(env, monkeypatch):
    client, store, tok = env
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: _products(3))
    before = len(store.list_catalogs(SHOP))
    sig = catalog.adhoc_sig(SHOP, "100,101")
    r = client.get(f"/catalog/for?sh={SHOP}&p=100,101&s={sig}&to=Grace")
    assert r.status_code == 200
    assert "Tan wool coat 0" in r.text and "Tan wool coat 1" in r.text
    assert "Tan wool coat 2" not in r.text          # only what was selected
    assert "Grace" in r.text                        # addressed to them
    assert r.headers.get("Cache-Control") == "no-store"
    assert len(store.list_catalogs(SHOP)) == before  # nothing was written


# ── the house profile bounds what may be offered ──────────────────────────────
def test_the_house_profile_reaches_the_suggest_prompt(env, monkeypatch):
    """The whole point of the questionnaire: the model is told what this merchant offers, and
    told not to offer anything else."""
    from halia import llm
    from halia.api.settings import settings_for
    import json as _json
    seen = {}
    client, store, tok = env
    cur = settings_for(SHOP)
    cur["vip_profile"] = {"services": ["engraving"], "perks": ["early_access"], "tone": "discreet"}
    store.save_settings(SHOP, _json.dumps(cur))
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(catalog, "_products", lambda shop, force=False: _products(2))
    monkeypatch.setattr(llm, "structured",
                        lambda s, u, sc, **k: seen.update(user=u) or {"picks": []})
    _seed_client()
    client.post("/v1/extension/suggest", json={"email": "grace@x.com"},
                headers={"X-Halia-Ext-Token": _ext(client, tok)})
    assert "Engraving" in seen["user"]
    assert "Early access to new arrivals" in seen["user"]
    assert "Offer only what is listed above" in seen["user"]
    assert "Alterations" not in seen["user"]        # not ticked, so never offered
