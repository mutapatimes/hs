"""SEO surface: structured data, canonical/OG tags, sitemap and robots."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from halia.api.app import app


@pytest.fixture()
def client():
    return TestClient(app)


def _ld(html: str) -> list:
    """Every parsed ld+json block on a page."""
    return [json.loads(b) for b in
            re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)]


def test_homepage_has_org_website_and_software_application(client):
    html = client.get("/").text
    types = {n.get("@type") for d in _ld(html) for n in d.get("@graph", [d])}
    assert {"Organization", "WebSite", "SoftwareApplication"} <= types
    # exactly one org graph (no duplicate injection despite the page referencing #organization)
    assert sum(1 for d in _ld(html) for n in d.get("@graph", [d])
               if n.get("@type") == "Organization") == 1


def test_marketing_page_gets_org_graph_injected(client):
    html = client.get("/pricing").text
    assert '"@type":"Organization"' in html and "#website" in html


def test_faq_page_emits_faqpage_matching_visible_questions(client):
    html = client.get("/faq").text
    faq = next(n for d in _ld(html) for n in d.get("@graph", [d]) if n.get("@type") == "FAQPage")
    visible = html.count('<details class="q">')
    assert len(faq["mainEntity"]) == visible and visible > 5
    q0 = faq["mainEntity"][0]
    assert q0["@type"] == "Question" and q0["acceptedAnswer"]["@type"] == "Answer"
    assert q0["acceptedAnswer"]["text"]           # answers are non-empty plain text


def test_blog_index_and_post_carry_canonical_og_and_schema(client):
    idx = client.get("/blog").text
    assert 'rel="canonical"' in idx and 'href="https://haliascore.com/blog"' in idx
    assert any(n.get("@type") == "Blog" for d in _ld(idx) for n in d.get("@graph", [d]))

    slug = re.search(r'/blog/([a-z0-9-]+)"', idx).group(1)
    post = client.get(f"/blog/{slug}").text
    assert f'rel="canonical" href="https://haliascore.com/blog/{slug}"' in post
    assert 'property="og:type" content="article"' in post
    assert 'name="twitter:card"' in post
    node = next(n for d in _ld(post) for n in d.get("@graph", [d]) if n.get("@type") == "BlogPosting")
    assert node["headline"] and node["datePublished"] and node["author"]["name"]
    assert any(n.get("@type") == "BreadcrumbList" for d in _ld(post) for n in d.get("@graph", [d]))


def test_sitemap_includes_blog_posts_excludes_gated_docs(client):
    xml = client.get("/sitemap.xml").text
    assert xml.startswith("<?xml")
    assert "<loc>https://haliascore.com/blog</loc>" in xml
    assert "/blog/" in xml and "<lastmod>" in xml          # posts with a lastmod
    assert "/docs" not in xml                              # docs are sign-in gated


def test_robots_disallows_private_areas_and_points_at_sitemap(client):
    body = client.get("/robots.txt").text
    for path in ("/app", "/console", "/admin", "/docs"):
        assert f"Disallow: {path}" in body
    assert "Sitemap: https://haliascore.com/sitemap.xml" in body
