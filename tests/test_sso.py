"""Single sign-on across the two internal surfaces: the console (/console) and the CMS (/admin).

One sign-in on either mints a shared `halia_session` cookie the other accepts; one sign-out clears
it for both. Each surface still needs its own enable-key to exist at all.
"""
import pytest
from fastapi.testclient import TestClient

from halia.api import content, shopify_auth
from halia.api.app import app
from halia.store import ShopStore


@pytest.fixture()
def both(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "sso.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr("halia.config.CONSOLE_KEY", "keyk")
    monkeypatch.setattr("halia.config.ADMIN_KEY", "keyk")
    content._bust()
    yield store
    content._bust()


def test_console_login_opens_the_cms(both):
    c = TestClient(app)
    r = c.post("/console/login", data={"key": "keyk"}, follow_redirects=False)
    assert "halia_session=" in r.headers.get("set-cookie", "")
    # The CMS is reachable without a separate /admin sign-in.
    assert "home.hero.title" in c.get("/admin").text
    # The console still works too, and its sidebar now links to the CMS.
    assert c.get("/console/data.json").status_code == 200
    assert "/admin" in c.get("/console").text


def test_cms_login_opens_the_console(both):
    c = TestClient(app)
    c.post("/admin/login", data={"key": "keyk"})
    assert c.get("/console/data.json").status_code == 200        # console open via shared session


def test_one_logout_closes_both(both):
    c = TestClient(app)
    c.post("/console/login", data={"key": "keyk"})
    assert c.get("/console/data.json").status_code == 200
    c.get("/admin/logout")                                       # sign out from the CMS side
    assert c.get("/console/data.json").status_code == 403        # console is closed too
    assert "Sign in" in c.get("/admin").text


def test_content_nav_hidden_when_cms_disabled(monkeypatch, tmp_path):
    store = ShopStore(db_path=tmp_path / "nocms.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr("halia.config.CONSOLE_KEY", "keyk")
    monkeypatch.setattr("halia.config.ADMIN_KEY", None)          # CMS off
    c = TestClient(app)
    c.post("/console/login", data={"key": "keyk"})
    assert 'href="/admin"' not in c.get("/console").text.replace("'", '"')
