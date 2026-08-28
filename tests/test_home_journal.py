"""The landing page carries the newest journal posts, filled at serve time; no posts, no section."""
from halia.api import blog


class _Store:
    def __init__(self, posts): self.posts = posts
    def list_posts(self, **kw): return self.posts[:kw.get("limit", 3)]


PAGE = "<p>x</p><!--journal:start--><section><div class=jgrid><!--halia:journal--></div></section><!--journal:end--><p>y</p>"


def test_latest_posts_become_cards():
    store = _Store([{"slug": "outer-signal-vs-mercana", "title": "OuterSignal, Mercana, Halia", "dek": "Three ways to read a book.",
                     "published_at": "2026-08-20T10:00:00+00:00", "body_html": "<p>" + "word " * 400 + "</p>", "cover_image_id": ""},
                    {"slug": "second", "title": "Second post", "dek": "", "published_at": "2026-08-01T10:00:00+00:00", "body_html": "<p>a</p>"}])
    html = blog.with_journal(PAGE, store)
    assert 'href="/blog/outer-signal-vs-mercana"' in html and "OuterSignal, Mercana, Halia" in html
    assert "Three ways to read a book." in html and "min read" in html
    assert html.count("jcard") == 2 and "<!--halia:journal-->" not in html


def test_no_posts_drops_the_section():
    html = blog.with_journal(PAGE, _Store([]))
    assert html == "<p>x</p><p>y</p>"


def test_pages_without_the_mark_are_untouched():
    assert blog.with_journal("<p>plain</p>", _Store([])) == "<p>plain</p>"
