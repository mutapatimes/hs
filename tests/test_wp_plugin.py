"""The WordPress plugin connects a store with one call: tenant, creds, webhook URL, sign-in link."""
import pytest
from fastapi.testclient import TestClient

from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.store import ShopStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "wp.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    monkeypatch.setattr(onboarding, "_validate_woo", lambda url, ck, cs, probe=None: (True, ""))
    sent = []
    monkeypatch.setattr(onboarding, "_send_welcome_signin_email", lambda *a, **k: sent.append(a) or True)
    yield TestClient(app), store, sent


def test_plugin_connect_creates_tenant_and_returns_links(env):
    client, store, sent = env
    r = client.post("/connect/woocommerce/plugin", json={
        "store_url": "https://maison.example/", "consumer_key": "ck_1", "consumer_secret": "cs_1",
        "site_name": "Maison", "email": "owner@maison.example"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["shop"] == "maison-example" and d["reconnected"] is False
    assert d["open_url"].endswith("/app?t=" + d["open_url"].rsplit("t=", 1)[1]) and len(d["open_url"].rsplit("t=", 1)[1]) > 20
    assert "/webhooks/orders/" in d["webhook_url"]
    assert "/c/" in d["capture_url"]  # the QR self-capture page, for the wp-admin till card
    assert dict(store.get_tenant("maison-example"))["kind"] == "woocommerce"
    assert store.get_woocommerce("maison-example")["consumer_key"] == "ck_1"
    assert sent and sent[0][0] == "owner@maison.example"


def test_plugin_reconnect_keeps_the_tenant_and_refreshes_keys(env):
    client, store, sent = env
    body = {"store_url": "https://maison.example", "consumer_key": "ck_1", "consumer_secret": "cs_1"}
    client.post("/connect/woocommerce/plugin", json=body)
    d = client.post("/connect/woocommerce/plugin", json={**body, "consumer_key": "ck_2", "consumer_secret": "cs_2"}).json()
    assert d["reconnected"] is True and d["open_url"].endswith("/app")
    assert store.get_woocommerce("maison-example")["consumer_key"] == "ck_2"


def test_plugin_connect_rejects_bad_input(env, monkeypatch):
    client, store, sent = env
    assert client.post("/connect/woocommerce/plugin", json={"store_url": "maison.example"}).status_code == 400
    monkeypatch.setattr(onboarding, "_validate_woo", lambda url, ck, cs, probe=None: (False, "401"))
    r = client.post("/connect/woocommerce/plugin", json={"store_url": "https://x.example", "consumer_key": "a", "consumer_secret": "b"})
    assert r.status_code == 400 and "could not reach" in r.json()["detail"]
