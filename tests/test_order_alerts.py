"""Real-time order-alert webhook + Web Push subscribe + settings plumbing."""
import json

import pytest
from fastapi.testclient import TestClient

from halia import notify
from halia.api import data, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "r.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    yield TestClient(app), store


def test_score_order_grades_a_strong_order(client):
    _, store = client
    store.create_tenant("shopr", "woocommerce", "Shop", "h")
    order = {"id": 5001, "total": "300.00", "date_created_gmt": "2026-06-30T10:00:00",
             "billing": {"first_name": "Sir James", "last_name": "Whitfield",
                         "email": "j@goldmansachs.com", "postcode": "W1K 1AB", "country": "GB"},
             "line_items": [{"quantity": 1}]}
    a = data.score_order("shopr", order)
    assert a and a["grade"] in ("A*", "A")
    assert a["order_id"] == "5001" and a["name"] == "Sir James Whitfield"


def test_order_webhook_adds_alert_and_dispatches(client, monkeypatch):
    c, store = client
    store.create_tenant("shopr", "woocommerce", "Shop", hash_token(new_token()))
    token = store.ensure_webhook_token("shopr", "tok-123")
    store.save_settings("shopr", json.dumps({"notify_grades": ["A*", "A"],
                                             "notify_email": "team@brand.com"}))
    store.add_push_sub("shopr", "https://push/ep", "p", "a")
    cache._alerts.pop("shopr", None)

    alert = {"order_id": "9001", "grade": "A*", "name": "Sir James", "score": 96,
             "signals": ["Work email"], "when": "2026-06-30"}
    monkeypatch.setattr(data, "score_order", lambda shop, p: alert)
    pushed, mailed = {}, {}
    monkeypatch.setattr(notify, "send_web_push", lambda subs, p: (pushed.update(p) or 1))
    monkeypatch.setattr(notify, "email_configured", lambda: True)
    monkeypatch.setattr(notify, "send_email", lambda to, subj, h: (mailed.update({"to": to, "subj": subj}) or True))

    r = c.post(f"/webhooks/orders/{token}", json={"id": 9001})
    assert r.status_code == 200
    assert any(a["order_id"] == "9001" for a in cache.get_alerts("shopr"))
    assert mailed["to"] == "team@brand.com" and "New A* order" in mailed["subj"]
    assert "New A* order" in pushed.get("title", "")


def test_webhook_ignores_low_grade(client, monkeypatch):
    c, store = client
    store.create_tenant("shopr", "woocommerce", "Shop", hash_token(new_token()))
    token = store.ensure_webhook_token("shopr", "tok-xyz")
    store.save_settings("shopr", json.dumps({"notify_grades": ["A*"]}))
    cache._alerts.pop("shopr", None)
    monkeypatch.setattr(data, "score_order",
                        lambda shop, p: {"order_id": "1", "grade": "B", "name": "x", "signals": []})
    c.post(f"/webhooks/orders/{token}", json={"id": 1})
    assert cache.get_alerts("shopr") == []


def test_push_subscribe_and_settings_expose_plumbing(client):
    c, store = client
    tok = new_token()
    store.create_tenant("shopr", "woocommerce", "Shop", hash_token(tok))
    c.cookies.set(COOKIE, tok)
    s = c.get("/v1/settings").json()
    assert s["webhook_url"].endswith("/webhooks/orders/" + store.get_webhook_token("shopr"))
    assert s["vapid_public"] and s["notify_email"] == ""
    assert c.post("/v1/push/subscribe",
                  json={"endpoint": "https://x/ep", "keys": {"p256dh": "p", "auth": "a"}}).status_code == 200
    assert store.push_subs("shopr")[0]["endpoint"] == "https://x/ep"
