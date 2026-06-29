"""Compliance webhooks: HMAC verification + GDPR/uninstall secret deletion."""
import base64
import hashlib
import hmac

from fastapi.testclient import TestClient

from halia.api.app import app
from halia.api.webhooks import verify_hmac
from halia.cache import cache
from halia.store import ShopStore

SECRET = "test-app-secret"
SHOP = "acme.myshopify.com"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_verify_hmac_unit():
    assert verify_hmac(b"hello", _sign(b"hello"), SECRET)
    assert not verify_hmac(b"hello", _sign(b"hello", "wrong"), SECRET)
    assert not verify_hmac(b"hello", "", SECRET)
    assert not verify_hmac(b"hello", _sign(b"hello"), None)


def test_webhook_rejects_invalid_hmac(monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    r = TestClient(app).post("/webhooks/shopify", content=b"{}",
                             headers={"X-Shopify-Hmac-Sha256": "nope",
                                      "X-Shopify-Topic": "shop/redact",
                                      "X-Shopify-Shop-Domain": SHOP})
    assert r.status_code == 401


def test_shop_redact_deletes_secrets_and_evicts(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    monkeypatch.setattr("halia.store.DB_PATH", str(tmp_path / "w.db"))
    ShopStore().save_shop(SHOP, "shpat_x")
    ShopStore().save_klaviyo(SHOP, "pk_y")
    cache.set(SHOP, [], {}, [])

    body = b'{"shop_domain":"acme.myshopify.com"}'
    r = TestClient(app).post("/webhooks/shopify", content=body,
                             headers={"X-Shopify-Hmac-Sha256": _sign(body),
                                      "X-Shopify-Topic": "shop/redact",
                                      "X-Shopify-Shop-Domain": SHOP})
    assert r.status_code == 200
    assert ShopStore().get_token(SHOP) is None and ShopStore().get_klaviyo(SHOP) is None
    assert cache.get(SHOP) is None


def test_customers_redact_evicts_cache_only(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    cache.set(SHOP, [1], {}, [])
    body = b'{"customer":{"id":1}}'
    r = TestClient(app).post("/webhooks/shopify", content=body,
                             headers={"X-Shopify-Hmac-Sha256": _sign(body),
                                      "X-Shopify-Topic": "customers/redact",
                                      "X-Shopify-Shop-Domain": SHOP})
    assert r.status_code == 200 and cache.get(SHOP) is None


def test_data_request_acknowledged(monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    body = b'{"customer":{"id":1}}'
    r = TestClient(app).post("/webhooks/shopify", content=body,
                             headers={"X-Shopify-Hmac-Sha256": _sign(body),
                                      "X-Shopify-Topic": "customers/data_request",
                                      "X-Shopify-Shop-Domain": SHOP})
    assert r.status_code == 200  # we hold no customer data — just acknowledge
