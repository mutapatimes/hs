"""Browser-extension API: per-tenant token + single-customer grade lookup (zero-retention)."""
import pytest
from fastapi.testclient import TestClient

from halia.api import extension, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "shopx"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "e.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "woocommerce", "Shop X", hash_token(tok))
    cache.clear()
    yield TestClient(app), store, tok
    cache.clear()


def _row(**kw):
    row = {"cid": "c1", "name": "Grace Ladoja", "email": "grace@x.com",
           "phone": "+44 7700 900123", "grade": "A*", "tier": "A1", "score": 98,
           "band": "lapsed", "known": True, "latent": "£12,400", "spend": 4200,
           "ordersCount": 3, "reco": "Lead with service.",
           "signals": [{"seg": "work", "d": "Work email: Goldman Sachs", "x": ""}],
           "adminUrl": "https://shopx/wp-admin/user-edit.php?user_id=1"}
    row.update(kw)
    return row


def _seed(rows):
    cache.set(SHOP, results=[], payload={"data": rows}, orders=[])


# ── token minting ───────────────────────────────────────────────────────────
def test_mint_returns_token_and_status_flips(env):
    client, store, tok = env
    assert client.get("/v1/extension/token", cookies={COOKIE: tok}).json()["enabled"] is False
    r = client.post("/v1/extension/token", cookies={COOKIE: tok})
    assert r.status_code == 200
    raw = r.json()["token"]
    assert raw and store.shop_for_extension_token(hash_token(raw)) == SHOP
    assert client.get("/v1/extension/token", cookies={COOKIE: tok}).json()["enabled"] is True


def test_mint_rotation_replaces_the_old_token(env):
    client, store, tok = env
    first = client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]
    second = client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]
    assert first != second
    assert store.shop_for_extension_token(hash_token(first)) is None
    assert store.shop_for_extension_token(hash_token(second)) == SHOP


# ── lookup auth ───────────────────────────────────────────────────────────────
def test_lookup_rejects_missing_or_bad_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/lookup", json={"email": "a@b.com"}).status_code == 401
    assert client.post("/v1/extension/lookup", json={"email": "a@b.com"},
                       headers={"X-Halia-Ext-Token": "nope"}).status_code == 401


def test_lookup_needs_an_identity(env):
    client, store, tok = env
    ext = client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]
    r = client.post("/v1/extension/lookup", json={}, headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 422


# ── lookup matching ───────────────────────────────────────────────────────────
def _ext_token(client, tok):
    return client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]


def test_lookup_by_email_returns_grade_reasons_latent_play_templates(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/lookup", json={"email": "GRACE@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["found"] is True
    assert d["grade"] == "A*" and d["latent"] == "£12,400"
    assert d["play"] == "sleeping" and d["playLabel"] == "Gone quiet"
    assert "Work email: Goldman Sachs" in d["reasons"]
    assert d["templates"] and "{first_name}" not in d["templates"][0]["body"]
    assert d["adminUrl"].startswith("https://shopx")


def test_lookup_by_cid_and_gid_forms(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(cid="gid://shopify/Customer/555")])
    for ident in ("555", "gid://shopify/Customer/555"):
        d = client.post("/v1/extension/lookup", json={"cid": ident},
                        headers={"X-Halia-Ext-Token": ext}).json()
        assert d["found"] is True and d["grade"] == "A*"


def test_lookup_by_phone_matches_on_national_digits(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/lookup", json={"phone": "07700900123"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["found"] is True and d["name"] == "Grace Ladoja"


def test_lookup_surfaces_last_order_and_open_basket(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(last="Mar 2026",
                cart={"value": 1800, "count": 2, "started": 1, "items": [], "url": "https://x/co"})])
    d = client.post("/v1/extension/lookup", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["last"] == "Mar 2026"
    assert d["cart"] == {"value": 1800, "count": 2, "url": "https://x/co"}


def test_lookup_ignores_empty_basket(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(cart={"value": 0, "count": 0})])
    d = client.post("/v1/extension/lookup", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["cart"] is None


def test_lookup_fresh_play_for_active_hidden_vic(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(known=False, band="active", tier="B", grade="B")])
    d = client.post("/v1/extension/lookup", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["play"] == "fresh" and d["hidden"] is True


def test_lookup_unknown_customer_is_not_found(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/lookup", json={"email": "stranger@nowhere.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d == {"found": False}


# ── unit helpers ──────────────────────────────────────────────────────────────
def test_play_of_rules():
    assert extension._play_of({"known": True}) == "sleeping"
    assert extension._play_of({"tier": "A", "ordersCount": 2, "band": "lapsed"}) == "sleeping"
    assert extension._play_of({"band": "active"}) == "fresh"
    assert extension._play_of({"band": "new"}) == "fresh"
    assert extension._play_of({"band": "cooling"}) == ""


def test_digits_takes_trailing_national_part():
    assert extension._digits("+44 7700 900123") == extension._digits("07700900123")
    assert extension._digits("123") == "123"  # too short to compare, returned as-is
