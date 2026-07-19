"""Shopify Billing: the plan catalogue, subscribe/activate/cancel, and the shared billing table."""
import pytest
from fastapi.testclient import TestClient

from halia import plans
from halia.api import billing_shopify, shopify_auth
from halia.api.app import app
from halia.api.shopify_auth import require_shop
from halia.store import ShopStore


# ── catalogue ────────────────────────────────────────────────────────────────────────
def test_catalogue_shape_and_feature_ladder():
    cat = {p["key"]: p for p in plans.public_catalogue()}
    assert list(cat) == ["free", "discovery", "signal", "atelier", "maison"]
    # Free sees the count but not the unmasking; Signal is the highlighted paid tier.
    feat = lambda k, key: next(f["included"] for f in cat[k]["features"] if f["label"].startswith(key))
    assert feat("free", "Hidden-VIC count") is True
    assert feat("free", "Unmask") is False
    assert feat("discovery", "Unmask") is True
    assert feat("signal", "Push to CRM") is True
    assert feat("discovery", "Push to CRM") is False
    assert cat["signal"]["highlighted"] is True
    assert cat["maison"]["custom"] is True and cat["maison"]["priceLabel"] == "Custom"
    assert cat["signal"]["priceLabel"] == "£500"


def test_billable_and_amount():
    assert plans.billable("signal") and plans.amount("signal") == 500.0
    assert not plans.billable("free") and plans.amount("free") is None
    assert not plans.billable("maison")            # custom = talk to us, not self-serve
    assert plans.recommended_key(9000) == "discovery"
    assert plans.recommended_key(40000) == "signal"
    assert plans.recommended_key(200000) == "atelier"


# ── API ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "b.db")
    store.save_shop("shopx", "offline-token")          # makes _token() truthy -> a Shopify tenant
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    app.dependency_overrides[require_shop] = lambda: "shopx"
    yield TestClient(app), store, monkeypatch
    app.dependency_overrides.pop(require_shop, None)


def test_status_lists_catalogue_and_defaults_to_free(api, monkeypatch):
    c, _, _ = api
    monkeypatch.setattr(billing_shopify, "active_subscription", lambda shop: None)
    j = c.get("/v1/plans/status").json()
    assert [p["key"] for p in j["plans"]] == ["free", "discovery", "signal", "atelier", "maison"]
    assert j["current"] == "free" and j["shopify"] is True and j["test"] is True


def test_subscribe_returns_confirmation_url(api, monkeypatch):
    c, _, _ = api
    seen = {}
    def fake_gql(shop, query, variables):
        seen["vars"] = variables
        return {"appSubscriptionCreate": {"userErrors": [],
                "confirmationUrl": "https://shopx/confirm/1", "appSubscription": {"id": "gid://s/1"}}}
    monkeypatch.setattr(billing_shopify, "_gql", fake_gql)
    r = c.post("/v1/plans/subscribe", json={"plan": "signal"})
    assert r.status_code == 200 and r.json()["confirmationUrl"] == "https://shopx/confirm/1"
    li = seen["vars"]["lineItems"][0]["plan"]["appRecurringPricingDetails"]
    assert li["price"] == {"amount": 500.0, "currencyCode": "GBP"} and li["interval"] == "EVERY_30_DAYS"
    assert seen["vars"]["test"] is True and seen["vars"]["name"] == "Signal"


def test_subscribe_rejects_free_custom_and_unknown(api):
    c, _, _ = api
    assert c.post("/v1/plans/subscribe", json={"plan": "free"}).status_code == 400
    assert c.post("/v1/plans/subscribe", json={"plan": "maison"}).status_code == 400
    assert c.post("/v1/plans/subscribe", json={"plan": "nope"}).status_code == 400


def test_subscribe_surfaces_shopify_user_errors(api, monkeypatch):
    c, _, _ = api
    monkeypatch.setattr(billing_shopify, "_gql", lambda *a: {
        "appSubscriptionCreate": {"userErrors": [{"field": "x", "message": "line item invalid"}]}})
    r = c.post("/v1/plans/subscribe", json={"plan": "discovery"})
    assert r.status_code == 502 and "line item invalid" in r.json()["detail"]


def test_activate_marks_active_and_redirects_into_admin(api, monkeypatch):
    c, store, _ = api
    monkeypatch.setattr(billing_shopify, "active_subscription",
                        lambda shop: {"id": "gid://s/9", "name": "Signal", "status": "ACTIVE"})
    r = c.get("/v1/plans/activate", params={"shop": "shopx"}, follow_redirects=False)
    assert r.status_code == 302 and "admin.shopify.com/store/shopx/apps/" in r.headers["location"]
    b = store.get_billing("shopx")
    assert b["status"] == "active" and b["subscription_id"] == "gid://s/9"


def test_activate_without_active_sub_marks_canceled(api, monkeypatch):
    c, store, _ = api
    monkeypatch.setattr(billing_shopify, "active_subscription", lambda shop: None)
    c.get("/v1/plans/activate", params={"shop": "shopx"}, follow_redirects=False)
    assert store.get_billing("shopx")["status"] == "canceled"


def test_cancel_downgrades_to_free(api, monkeypatch):
    c, store, _ = api
    monkeypatch.setattr(billing_shopify, "active_subscription",
                        lambda shop: {"id": "gid://s/9", "name": "Signal", "status": "ACTIVE"})
    monkeypatch.setattr(billing_shopify, "_gql",
                        lambda *a: {"appSubscriptionCancel": {"userErrors": []}})
    r = c.post("/v1/plans/cancel")
    assert r.status_code == 200 and r.json()["current"] == "free"
    assert store.get_billing("shopx")["status"] == "canceled"


def test_current_plan_reflects_active_subscription(api, monkeypatch):
    c, _, _ = api
    monkeypatch.setattr(billing_shopify, "active_subscription",
                        lambda shop: {"id": "gid://s/2", "name": "Atelier", "status": "ACTIVE"})
    assert c.get("/v1/plans/status").json()["current"] == "atelier"
