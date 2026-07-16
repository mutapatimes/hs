"""Platform-aware dashboard link in emails: hosted /app vs embedded Shopify admin URL."""
import halia.config as config
from halia.api import onboarding as o


def test_hosted_default_when_no_app_handle(monkeypatch):
    monkeypatch.setattr(config, "SHOPIFY_APP_HANDLE", None)
    monkeypatch.setattr(config, "HALIA_APP_URL", "https://haliascore.com")
    # even asking for embedded, with no handle configured we stay on the safe hosted link
    assert o._dashboard_url("acme.myshopify.com", embedded=True) == "https://haliascore.com/app"


def test_embedded_shopify_links_into_admin(monkeypatch):
    monkeypatch.setattr(config, "SHOPIFY_APP_HANDLE", "halia")
    assert o._dashboard_url("acme.myshopify.com", embedded=True) == \
        "https://admin.shopify.com/store/acme/apps/halia"


def test_hosted_shopify_and_woo_use_app(monkeypatch):
    monkeypatch.setattr(config, "SHOPIFY_APP_HANDLE", "halia")
    monkeypatch.setattr(config, "HALIA_APP_URL", "https://haliascore.com")
    assert o._dashboard_url("acme.myshopify.com", embedded=False).endswith("/app")   # self-serve Shopify
    assert o._dashboard_url("glen-norah", embedded=True).endswith("/app")            # non-Shopify, never admin


def test_custom_hosted_path_preserved(monkeypatch):
    monkeypatch.setattr(config, "HALIA_APP_URL", "https://haliascore.com")
    assert o._dashboard_url("acme.myshopify.com", "/app?t=xyz", embedded=False) == \
        "https://haliascore.com/app?t=xyz"


def test_embedded_detection_from_tenant(monkeypatch):
    from halia.store import ShopStore
    monkeypatch.setattr(ShopStore, "get_tenant",
                        lambda self, s: {"kind": "shopify"} if s == "embedded.myshopify.com"
                        else {"kind": "shopify", "token_hash": "abc"})
    assert o._is_embedded_shopify("embedded.myshopify.com") is True     # no token_hash -> embedded
    assert o._is_embedded_shopify("selfserve.myshopify.com") is False   # has hash -> hosted
    assert o._is_embedded_shopify("glen-norah") is False                # not Shopify at all
