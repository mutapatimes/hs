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
    yield TestClient(app), store, ext, tok


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


# ── clean capture + alerts + the settings-preservation fix ───────────────────

def test_capture_normalises_email_and_postcode(env, monkeypatch):
    client, _, ext, _ = env
    fake = FakeShopify()
    monkeypatch.setattr(capture_mod, "_gql", fake)
    r = _post(client, ext, {"email": "  Grace@GMAIL.com ", "postcode": "sw1a1aa",
                            "country": "UK", "first_name": "Grace"})
    assert r.status_code == 200
    create_vars = next(v for q, v in fake.calls if "customerCreate" in q)
    assert create_vars["input"]["email"] == "grace@gmail.com"
    assert create_vars["input"]["addresses"][0]["zip"] == "SW1A 1AA"


def test_check_endpoints_suggest_fixes(env, monkeypatch):
    client, _, ext, _ = env
    from halia import capture_quality as cq
    monkeypatch.setattr(cq, "_domain_resolves", lambda d: True)
    capture_mod._SLUG_CACHE.clear()
    slug = capture_mod._slug_for(SHOP)
    d = client.post(f"/c/{slug}/check", json={"email": "a@gamil.com", "postcode": "w1j7bu"}).json()
    assert d["email_suggestion"] == "a@gmail.com" and d["postcode"] == "W1J 7BU"
    # seat-authed twin for the iOS handover form
    d = client.post("/v1/capture/check", json={"email": "a@hotmial.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["email_suggestion"] == "a@hotmail.com"
    assert client.post("/v1/capture/check", json={"email": "x@y.com"}).status_code == 401


def test_qr_capture_alerts_team_on_high_grade(env, monkeypatch):
    client, store, ext, _ = env
    from halia.api import capture_alerts
    monkeypatch.setattr(capture_mod, "_gql", FakeShopify())
    sent = []
    monkeypatch.setattr(capture_alerts.notify, "send_email", lambda *a, **k: sent.append(("email", a)) or True)
    monkeypatch.setattr(capture_alerts.notify, "email_configured", lambda: True)
    monkeypatch.setattr(capture_alerts.notify, "send_web_push", lambda *a, **k: sent.append(("push", a)) or 1)
    store.save_settings(SHOP, '{"capture_alerts": true, "notify_grades": ["A*", "A"], '
                              '"notify_emails": ["team@shopx.com"]}')
    # a high-signal record: prime-postcode capture grades A-band via the real engine
    monkeypatch.setattr(capture_mod, "_score_capture",
                        lambda cid, body, email, phone: {"grade": "A*", "signals": ["Prime postcode"]})
    capture_mod._SLUG_CACHE.clear()
    slug = capture_mod._slug_for(SHOP)
    r = client.post(f"/c/{slug}", json={"email": "vic@x.com", "first_name": "Grace"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert any(k == "email" for k, _ in sent)


def test_qr_capture_low_grade_stays_quiet(env, monkeypatch):
    client, store, ext, _ = env
    from halia.api import capture_alerts
    monkeypatch.setattr(capture_mod, "_gql", FakeShopify())
    sent = []
    monkeypatch.setattr(capture_alerts.notify, "send_email", lambda *a, **k: sent.append(1) or True)
    monkeypatch.setattr(capture_alerts.notify, "email_configured", lambda: True)
    store.save_settings(SHOP, '{"notify_emails": ["team@shopx.com"]}')
    monkeypatch.setattr(capture_mod, "_score_capture",
                        lambda cid, body, email, phone: {"grade": "C", "signals": []})
    capture_mod._SLUG_CACHE.clear()
    slug = capture_mod._slug_for(SHOP)
    client.post(f"/c/{slug}", json={"email": "someone@x.com"})
    assert sent == []


def test_repeat_capture_never_realerts(env, monkeypatch):
    client, store, ext, _ = env
    from halia.api import capture_alerts
    monkeypatch.setattr(capture_mod, "_gql", FakeShopify(
        existing={"id": "gid://shopify/Customer/5", "email": "vic@x.com", "phone": "", "tags": []}))
    sent = []
    monkeypatch.setattr(capture_alerts.notify, "send_email", lambda *a, **k: sent.append(1) or True)
    monkeypatch.setattr(capture_alerts.notify, "email_configured", lambda: True)
    store.save_settings(SHOP, '{"notify_emails": ["team@shopx.com"]}')
    monkeypatch.setattr(capture_mod, "_score_capture",
                        lambda cid, body, email, phone: {"grade": "A*", "signals": []})
    capture_mod._SLUG_CACHE.clear()
    slug = capture_mod._slug_for(SHOP)
    client.post(f"/c/{slug}", json={"email": "vic@x.com"})   # created=False
    assert sent == []


def test_settings_save_preserves_capture_slug_and_brand(env):
    """The settings save rebuilds the blob from a whitelist; slug and brand must survive
    (before the fix, a routine save silently destroyed them, breaking printed QRs)."""
    import json as _json

    from halia.api.tenant_auth import COOKIE

    client, store, _, tok = env
    capture_mod._SLUG_CACHE.clear()
    slug = capture_mod._slug_for(SHOP)
    raw = _json.loads(store.get_settings_raw(SHOP))
    raw["brand"] = "storeconcierge"
    store.save_settings(SHOP, _json.dumps(raw))

    r = client.post("/v1/settings", json={"vic_threshold": 500}, cookies={COOKIE: tok})
    assert r.status_code == 200

    saved = _json.loads(store.get_settings_raw(SHOP))
    assert saved["capture_slug"] == slug
    assert saved["brand"] == "storeconcierge"
    assert saved["capture_alerts"] is True      # default carried into the blob


# ── follow-up with a date ────────────────────────────────────────────────────
class _PipeSink:
    def __init__(self): self.meta, self.tags = {}, []
    def get_metafield(self, cid, key, namespace="halia"): return self.meta.get((cid, key))
    def set_metafield(self, cid, key, value, *a, **k): self.meta[(cid, key)] = value
    def tag_customer(self, cid, tags): self.tags.append(("+", tags))
    def untag_customer(self, cid, tags): self.tags.append(("-", tags))


def test_followup_accepts_a_due_date_and_stores_it(env, monkeypatch):
    import json
    from halia.api import board
    sink = _PipeSink()
    monkeypatch.setattr(board, "_sink", lambda shop: sink)
    client, store, ext, _ = env
    r = client.post("/v1/capture/followup", json={"customer_id": "gid://shopify/Customer/9", "note": "Wedding on 12 June", "due": "2027-06-07"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200 and r.json()["due"] == "2027-06-07"
    pipe = json.loads(sink.meta[("9", "pipeline")])
    assert pipe["due"] == "2027-06-07"
    assert pipe["activity"][-1]["note"].startswith("Follow up week of 2027-06-07: Wedding on 12 June")


def test_followup_rejects_a_bad_due(env, monkeypatch):
    from halia.api import board
    monkeypatch.setattr(board, "_sink", lambda shop: _PipeSink())
    client, store, ext, _ = env
    r = client.post("/v1/capture/followup", json={"customer_id": "9", "note": "x", "due": "next june"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 422
