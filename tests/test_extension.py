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


# ── standing toolbar context ──────────────────────────────────────────────────
def test_context_requires_token(env):
    client, store, tok = env
    assert client.get("/v1/extension/context").status_code == 401
    assert client.get("/v1/extension/context",
                      headers={"X-Halia-Ext-Token": "nope"}).status_code == 401


def test_context_returns_templates_and_running_campaigns(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    import json as _json
    store.save_campaign("camp_now", SHOP, "Spring Preview", "2000-01-01", "2999-01-01",
                        _json.dumps({"tiers": [], "signals": [], "members": ["a", "b"]}))
    store.save_campaign("camp_old", SHOP, "Old Sale", "2000-01-01", "2000-02-01",
                        _json.dumps({"tiers": [], "signals": [], "members": []}))
    d = client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": ext}).json()
    # templates keep {first_name} for the toolbar to fill per client
    assert d["templates"] and any("{first_name}" in t["body"] for t in d["templates"])
    running = [c for c in d["campaigns"] if c["running"]]
    assert [c["id"] for c in running] == ["camp_now"]
    now = next(c for c in d["campaigns"] if c["id"] == "camp_now")
    assert now["utm"] == "spring-preview" and now["members"] == 2
    assert d["campaigns"][0]["id"] == "camp_now"  # running sorts first


# ── product search / cart builder ─────────────────────────────────────────────
def test_products_requires_token_and_is_shopify_only(env):
    client, store, tok = env  # woo tenant, no Shopify admin token
    assert client.get("/v1/extension/products").status_code == 401
    ext = _ext_token(client, tok)
    d = client.get("/v1/extension/products?q=scarf", headers={"X-Halia-Ext-Token": ext}).json()
    assert d == {"products": [], "cart_base": None}


# ── inbox triage batch ────────────────────────────────────────────────────────
def test_batch_grades_known_emails_and_omits_others(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(email="grace@x.com", known=False, band="lapsed", tier="A1"),
           _row(cid="c2", email="ben@x.com", grade="B", tier="B", known=False, band="active")])
    d = client.post("/v1/extension/batch",
                    json={"emails": ["GRACE@x.com", "ben@x.com", "stranger@nowhere.com"]},
                    headers={"X-Halia-Ext-Token": ext}).json()
    g = d["grades"]
    assert set(g) == {"grace@x.com", "ben@x.com"}         # unknown omitted
    assert g["grace@x.com"]["grade"] == "A*" and g["ben@x.com"]["grade"] == "B"
    assert g["ben@x.com"]["play"] == "fresh"


def test_batch_is_warm_only_and_needs_a_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/batch", json={"emails": ["a@b.com"]}).status_code == 401
    ext = _ext_token(client, tok)  # no cache seeded -> warm miss returns empty, never syncs
    d = client.post("/v1/extension/batch", json={"emails": ["a@b.com"]},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d == {"grades": {}}


# ── one-click actions ─────────────────────────────────────────────────────────
def test_action_requires_token_and_cid(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    assert client.post("/v1/extension/action", json={"action": "pipeline", "cid": "1"}).status_code == 401
    assert client.post("/v1/extension/action", json={"action": "pipeline"},
                       headers={"X-Halia-Ext-Token": ext}).status_code == 422


def test_action_campaign_add_appends_member(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    import json as _json
    store.save_campaign("camp1", SHOP, "Spring", "2025-03-01", "2025-05-31",
                        _json.dumps({"tiers": [], "signals": [], "members": []}))
    r = client.post("/v1/extension/action",
                    json={"action": "campaign_add", "campaign_id": "camp1", "cid": "c9"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200 and r.json()["count"] == 1
    got = _json.loads(store.get_campaign("camp1", SHOP)["config_json"])
    assert got["members"] == ["c9"]
    # idempotent: adding again does not duplicate
    client.post("/v1/extension/action",
                json={"action": "campaign_add", "campaign_id": "camp1", "cid": "c9"},
                headers={"X-Halia-Ext-Token": ext})
    got2 = _json.loads(store.get_campaign("camp1", SHOP)["config_json"])
    assert got2["members"] == ["c9"]


def test_action_pipeline_needs_shopify_writeback(env):
    client, store, tok = env  # SHOP is a woocommerce tenant here
    ext = _ext_token(client, tok)
    r = client.post("/v1/extension/action", json={"action": "pipeline", "cid": "c1"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 400  # pipeline is Shopify-write-back only


def test_action_note_requires_text_and_shopify(env):
    client, store, tok = env  # woo tenant
    ext = _ext_token(client, tok)
    # empty note -> 422 (checked before the Shopify sink)
    assert client.post("/v1/extension/action", json={"action": "note", "cid": "c1", "note": "  "},
                       headers={"X-Halia-Ext-Token": ext}).status_code == 422
    # real note on a non-Shopify tenant -> 400 (write-back only)
    assert client.post("/v1/extension/action",
                       json={"action": "note", "cid": "c1", "note": "Prefers navy"},
                       headers={"X-Halia-Ext-Token": ext}).status_code == 400


def test_action_rejects_unknown(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    r = client.post("/v1/extension/action", json={"action": "wat", "cid": "c1"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 422


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
