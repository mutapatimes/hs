"""Mini-CMS: override injection, block scanning, and the gated /admin editor."""
import pytest
from fastapi.testclient import TestClient

from halia.api import content, shopify_auth
from halia.api.app import app
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "c.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr("halia.config.ADMIN_KEY", "s3cret")
    content._bust()
    yield TestClient(app), store
    content._bust()


def test_apply_overrides_default_then_override(client):
    _, store = client
    html = '<h1><!--cms:home.hero.title-->Default<!--/cms--></h1>'
    assert content.apply_overrides(html) == html          # no override -> unchanged
    store.set_content("home.hero.title", "New headline")
    content._bust()
    out = content.apply_overrides(html)
    assert "New headline" in out and "Default" not in out
    assert "<!--cms:home.hero.title-->" in out             # markers kept -> still editable later


def test_scan_finds_marked_blocks(client):
    keys = {b["key"] for b in content.scan_blocks()}
    assert {"home.hero.eyebrow", "home.hero.title", "home.hero.sub",
            "solutions.hero.title", "clienteling.hero.title"} <= keys


def test_email_draft_is_a_cms_editable_block(client):
    _, store = client
    keys = {b["key"] for b in content.scan_blocks()}
    assert {"email.draft.subject", "email.draft.body"} <= keys      # shows up in /admin
    d = content.draft_template()
    assert d["subject"] == "A personal note" and "{first_name}" in d["body"]   # defaults
    store.set_content("email.draft.subject", "A note from Aubin")
    content._bust()
    assert content.draft_template()["subject"] == "A note from Aubin"          # override wins


def test_homepage_serves_default_then_override(client):
    c, store = client
    assert "A sea of records" in c.get("/").text          # default renders; marker is a comment
    store.set_content("home.hero.sub", "Edited subcopy here.")
    content._bust()
    body = c.get("/").text
    # The marked hero block now carries the override (the meta description is a separate copy).
    assert "<!--cms:home.hero.sub-->Edited subcopy here.<!--/cms-->" in body


def test_other_pages_pick_up_overrides(client):
    c, store = client
    store.set_content("solutions.hero.title", "Made for luxury.")
    content._bust()
    assert "Made for luxury." in c.get("/solutions").text


def test_admin_login_required_and_key_checked(client):
    c, _ = client
    assert c.post("/admin/login", data={"key": "nope"}).status_code == 401
    r = c.post("/admin/login", data={"key": "s3cret"}, follow_redirects=False)
    assert r.status_code == 303 and "halia_admin=" in r.headers.get("set-cookie", "")
    # Now the editor renders and lists a known block.
    assert "home.hero.title" in c.get("/admin").text


def test_admin_save_sets_and_revert_deletes(client):
    c, store = client
    c.post("/admin/login", data={"key": "s3cret"})
    c.post("/admin/save", data={"blk_home.hero.title": "Brand new"}, follow_redirects=False)
    assert store.get_content_all().get("home.hero.title") == "Brand new"
    default = next(b["default"] for b in content.scan_blocks() if b["key"] == "home.hero.title")
    c.post("/admin/save", data={"blk_home.hero.title": default}, follow_redirects=False)
    assert "home.hero.title" not in store.get_content_all()   # reverting drops the override


def test_admin_save_rejected_without_session(client):
    c, _ = client
    assert c.post("/admin/save", data={"blk_home.hero.title": "x"}).status_code == 403


def test_admin_disabled_without_key(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.ADMIN_KEY", None)
    assert "HALIA_ADMIN_KEY" in c.get("/admin").text
