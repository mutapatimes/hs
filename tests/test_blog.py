"""Native blog CMS: store CRUD, public rendering (pagination/sort/tags), drafts, admin gating."""
import pytest
from fastapi.testclient import TestClient

from halia.api import blog, shopify_auth
from halia.api.app import app
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "blog.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)   # every surface shares this store
    blog.seed_blog()                                          # seed into the test store
    return TestClient(app), store


def _post(slug, title="A post", status="published", tags="", published_at="2026-07-08T09:00:00+00:00"):
    return {"slug": slug, "title": title, "dek": "dek", "body_html": "<p>body words here now</p>",
            "author": "The Halia team", "cover_image_id": None, "tags": tags,
            "status": status, "published_at": published_at}


# ── store CRUD ────────────────────────────────────────────────────────────────────
def test_store_crud_and_filters(tmp_path):
    s = ShopStore(db_path=tmp_path / "s.db")
    s.upsert_post(_post("a", "Alpha", tags="news,compare", published_at="2026-01-01T00:00:00+00:00"))
    s.upsert_post(_post("b", "Beta", tags="news", published_at="2026-03-01T00:00:00+00:00"))
    s.upsert_post(_post("d", "Draft", status="draft", published_at=None))

    assert s.count_posts(published_only=True) == 2
    assert s.count_posts(published_only=False) == 3
    assert [p["slug"] for p in s.list_posts(sort="newest")] == ["b", "a"]
    assert [p["slug"] for p in s.list_posts(sort="oldest")] == ["a", "b"]
    assert [p["slug"] for p in s.list_posts(tag="compare")] == ["a"]
    # pagination
    assert [p["slug"] for p in s.list_posts(limit=1, offset=0)] == ["b"]
    assert [p["slug"] for p in s.list_posts(limit=1, offset=1)] == ["a"]
    assert s.get_post("a")["title"] == "Alpha"
    s.delete_post("a")
    assert s.get_post("a") is None and s.count_posts(published_only=False) == 2


def test_image_roundtrip(tmp_path):
    s = ShopStore(db_path=tmp_path / "img.db")
    s.save_image(b"\x89PNG\r\n\x1a\nbytes", "image/png", "id1")
    got = s.get_image("id1")
    assert got["mime"] == "image/png" and got["data"] == b"\x89PNG\r\n\x1a\nbytes"
    assert s.get_image("missing") is None


# ── public rendering ──────────────────────────────────────────────────────────────
def test_index_shows_seeded_comparison(client):
    c, _ = client
    r = c.get("/blog")
    assert r.status_code == 200
    assert "The Halia Journal" in r.text
    assert "Influence, or net worth" in r.text


def test_comparison_post_renders_with_table(client):
    c, _ = client
    r = c.get(f"/blog/{blog.COMPARISON_SLUG}")
    assert r.status_code == 200
    assert "Mercana" in r.text and "OuterSignal" in r.text
    assert 'class="cmp"' in r.text                         # the comparison table rendered
    assert "High-net-worth private clients" in r.text      # the differentiator row


def test_pagination(client, monkeypatch):
    c, store = client
    # seed one already exists; add enough to force a second page
    for i in range(blog.PAGE_SIZE + 2):
        store.upsert_post(_post(f"p{i:02d}", f"Post {i}",
                                published_at=f"2026-02-{i+1:02d}T00:00:00+00:00"))
    total = store.count_posts(published_only=True)
    assert total >= blog.PAGE_SIZE + 1
    p1 = c.get("/blog")
    assert p1.status_code == 200 and 'class="pager"' in p1.text  # pager shown
    p2 = c.get("/blog?page=2")
    assert p2.status_code == 200


def test_sort_and_tag_filters_serve(client):
    c, _ = client
    assert c.get("/blog?sort=oldest").status_code == 200
    assert c.get("/blog?tag=comparison").status_code == 200


def test_draft_hidden_from_public(client):
    c, store = client
    store.upsert_post(_post("secret", "Secret", status="draft", published_at=None))
    assert c.get("/blog/secret").status_code == 404
    # and it does not appear on the index
    assert "Secret" not in c.get("/blog").text


def test_missing_post_404(client):
    c, _ = client
    assert c.get("/blog/nope").status_code == 404


def test_image_route_serves_bytes(client):
    c, store = client
    store.save_image(b"hello-bytes", "image/jpeg", "abc")
    r = c.get("/blog/img/abc")
    assert r.status_code == 200 and r.content == b"hello-bytes"
    assert r.headers["content-type"].startswith("image/jpeg")
    assert c.get("/blog/img/missing").status_code == 404


# ── admin gating ──────────────────────────────────────────────────────────────────
def test_admin_blog_requires_key(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.ADMIN_KEY", None)
    r = c.get("/admin/blog", follow_redirects=False)
    assert r.status_code == 303                            # bounced to /admin (disabled)


def test_admin_blog_authed_flow(client, monkeypatch):
    c, store = client
    monkeypatch.setattr("halia.config.ADMIN_KEY", "secret-key")
    # sign in via the shared content-editor login (sets the admin cookie)
    login = c.post("/admin/login", data={"key": "secret-key"}, follow_redirects=False)
    assert login.status_code == 303
    lst = c.get("/admin/blog")
    assert lst.status_code == 200 and "New post" in lst.text
    editor = c.get("/admin/blog/new")
    assert editor.status_code == 200 and "Quill" in editor.text
    # create a post
    save = c.post("/admin/blog/save", data={
        "orig_slug": "", "title": "My New Post", "slug": "", "dek": "d",
        "author": "Me", "tags": "x", "body_html": "<p>hi</p>", "cover_image_id": "",
        "published": "on"}, follow_redirects=False)
    assert save.status_code == 303
    assert store.get_post("my-new-post") is not None
    assert c.get("/blog/my-new-post").status_code == 200
    # delete it
    dele = c.post("/admin/blog/delete", data={"slug": "my-new-post"}, follow_redirects=False)
    assert dele.status_code == 303 and store.get_post("my-new-post") is None


def test_seed_is_idempotent(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "seed.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    blog.seed_blog()
    blog.seed_blog()
    assert store.count_posts(published_only=False) == 1
