"""In-store capture: seat-authed write-through to Shopify + instant score, zero retention."""
import pytest
from fastapi.testclient import TestClient

from halia.api import capture as capture_mod
from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import hash_token, new_token
from halia.store import ShopStore

SHOP = "shopx"


class FakeShopify:
    """Records every GraphQL call; canned answers per operation."""

    def __init__(self, existing=None):
        self.calls = []
        self.existing = existing

    def __call__(self, shop, token, query, variables):
        self.calls.append((query, variables))
        if "customers(first: 1" in query:
            nodes = [self.existing] if self.existing else []
            return {"customers": {"nodes": nodes}}
        if "customerCreate" in query:
            return {"customerCreate": {"customer": {"id": "gid://shopify/Customer/9"},
                                       "userErrors": []}}
        if "customerUpdate" in query:
            return {"customerUpdate": {"customer": {"id": variables["input"]["id"]},
                                       "userErrors": []}}
        return {}

    def ops(self):
        keys = []
        for q, _ in self.calls:
            for op in ("customers(first: 1", "customerCreate", "customerUpdate", "tagsAdd",
                       "metafieldsSet", "customerEmailMarketingConsentUpdate",
                       "customerSmsMarketingConsentUpdate"):
                if op in q:
                    keys.append(op)
        return keys


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "c.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Shop X", hash_token(tok))
    ext = new_token()
    store.set_extension_token(SHOP, hash_token(ext))
    monkeypatch.setattr(capture_mod, "get_valid_token", lambda shop: "shptoken")
    yield TestClient(app), store, ext, monkeypatch


def _post(client, ext, body):
    return client.post("/v1/capture", json=body, headers={"X-Halia-Ext-Token": ext})


def test_create_writes_profile_consent_and_scores(env, monkeypatch):
    client, store, ext, _ = env
    fake = FakeShopify()
    monkeypatch.setattr(capture_mod, "_gql", fake)
    r = _post(client, ext, {
        "first_name": "Grace", "last_name": "Ladoja", "email": "grace@x.com",
        "phone": "+44 7700 900123", "postcode": "SW1A 1AA", "channel": "handover",
        "sizes": "IT 38", "consent": {"email_marketing": True, "sms_marketing": False},
    })
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True and out["created"] is True
    assert out["customer_id"] == "gid://shopify/Customer/9"
    assert out.get("grade")  # scored in memory
    ops = fake.ops()
    assert "customerCreate" in ops and "metafieldsSet" in ops
    assert "customerEmailMarketingConsentUpdate" in ops       # opted in
    assert "customerSmsMarketingConsentUpdate" not in ops     # did not opt in
    # tags ride the create input
    create_vars = next(v for q, v in fake.calls if "customerCreate" in q)
    assert "halia-captured" in create_vars["input"]["tags"]


def test_dedupe_updates_never_duplicates(env, monkeypatch):
    client, store, ext, _ = env
    fake = FakeShopify(existing={"id": "gid://shopify/Customer/5",
                                 "email": "grace@x.com", "phone": "", "tags": []})
    monkeypatch.setattr(capture_mod, "_gql", fake)
    r = _post(client, ext, {"email": "grace@x.com", "first_name": "Grace",
                            "phone": "+44 7700 900123"})
    out = r.json()
    assert out["created"] is False and out["customer_id"] == "gid://shopify/Customer/5"
    ops = fake.ops()
    assert "customerUpdate" in ops and "customerCreate" not in ops
    assert "tagsAdd" in ops
    # never clobbers the existing email with a duplicate-key write
    update_vars = next(v for q, v in fake.calls if "customerUpdate" in q)
    assert "email" not in update_vars["input"]
    assert update_vars["input"]["phone"] == "+44 7700 900123"  # new field still lands


def test_needs_email_or_phone(env, monkeypatch):
    client, _, ext, _ = env
    monkeypatch.setattr(capture_mod, "_gql", FakeShopify())
    assert _post(client, ext, {"first_name": "Grace"}).status_code == 422


def test_read_only_tenant_409(env, monkeypatch):
    client, _, ext, _ = env
    monkeypatch.setattr(capture_mod, "get_valid_token", lambda shop: None)
    r = _post(client, ext, {"email": "a@b.com"})
    assert r.status_code == 409


def test_requires_extension_token(env):
    client, _, _, _ = env
    assert client.post("/v1/capture", json={"email": "a@b.com"}).status_code == 401


def test_qr_link_page_and_submit(env, monkeypatch):
    client, store, ext, _ = env
    fake = FakeShopify()
    monkeypatch.setattr(capture_mod, "_gql", fake)
    capture_mod._SLUG_CACHE.clear()
    r = client.get("/v1/capture/link", headers={"X-Halia-Ext-Token": ext})
    url = r.json()["url"]
    slug = url.rsplit("/c/", 1)[1].split("?")[0]
    # the public page is store-branded
    page = client.get(f"/c/{slug}")
    assert page.status_code == 200 and "Shop X" in page.text
    # a submit runs the same pipeline but returns a plain thank-you (no grade leak)
    r = client.post(f"/c/{slug}", json={"email": "new@x.com", "channel": "qr", "by": "Sarah"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert "customerCreate" in fake.ops()
    # the slug is stable across calls
    again = client.get("/v1/capture/link", headers={"X-Halia-Ext-Token": ext}).json()["url"]
    assert slug in again


def test_qr_unknown_slug_404(env):
    client, _, _, _ = env
    capture_mod._SLUG_CACHE.clear()
    assert client.get("/c/nope").status_code == 404
    assert client.post("/c/nope", json={"email": "a@b.com"}).status_code == 404

