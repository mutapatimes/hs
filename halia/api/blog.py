"""Native blog CMS: public reading + operator authoring, all inside the FastAPI app.

Posts live in the ``blog_posts`` table (company content, not customer data); images live in
``blog_images`` (base64 in the DB, so they survive Render's ephemeral disk). Public pages
(``/blog``, ``/blog/<slug>``) are server-rendered from the DB with pagination + sorting and reuse
the marketing site's light-theme chrome. Authoring lives at ``/admin/blog`` behind the same
``HALIA_ADMIN_KEY`` gate as the content editor, with a WYSIWYG (Quill) body editor that stores HTML.

The first post (a factual OuterSignal / Mercana comparison) is seeded on startup if absent, so the
section ships with content; it stays fully editable in the CMS.
"""
from __future__ import annotations

import html as _html
import math
import re
import secrets

from fastapi import Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from halia.api import console
from halia.api.content import _admin_ok
from halia.api.shopify_auth import shop_store

# Reuse the generated marketing chrome (light theme, Cormorant Garamond + Inter). These carry the
# site nav/footer (with the Blog link) so blog pages match every other page.
from scripts.build_solutions_pages import _footer, _nav, _SCRIPT

_ASTER = "&#8258;"
PAGE_SIZE = 9
COMPARISON_SLUG = "influence-or-net-worth-halia-vs-outersignal-mercana"
ALTRATA_SLUG = "stored-or-scored-halia-vs-altrata"
JULIUS_BAER_SLUG = "julius-baer-wealth-report-2026-the-quiet-buyer"
KNIGHT_FRANK_SLUG = "knight-frank-wealth-report-2025-wealth-is-moving"

_SCRIPT_RE = re.compile(r"<(script|iframe)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _sanitize(html_text: str) -> str:
    """Strip <script>/<iframe> from operator-authored HTML (defense-in-depth; it renders public)."""
    return _SCRIPT_RE.sub("", html_text or "")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "post"


def _read_min(body_html: str) -> int:
    words = len(_TAG_RE.sub(" ", body_html or "").split())
    return max(1, round(words / 200))


def _date_label(iso: str | None) -> str:
    """'2026-07-08T…' -> '8 July 2026'. Falls back to the raw string."""
    if not iso:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    if not m:
        return iso
    months = ["", "January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{d} {months[mo]} {y}"


def _tags(post: dict) -> list[str]:
    return [t.strip() for t in (post.get("tags") or "").split(",") if t.strip()]


# ── page shell ───────────────────────────────────────────────────────────────────
_BLOG_CSS = """
  :root{--bg:#f5f2ea;--bg-2:#efeadd;--ink:#1a1712;--mute:#615b50;--faint:#9a9385;--gold:#7a7363;
    --line:rgba(20,18,12,.14);--line-2:rgba(20,18,12,.07);
    --serif:'Cormorant Garamond',Georgia,serif;--sans:'Inter',-apple-system,system-ui,sans-serif}
  *{box-sizing:border-box}html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
  a{color:inherit;text-decoration:none}::selection{background:#1a1712;color:#f5f2ea}
  .wrap{max-width:1120px;margin:0 auto;padding:0 40px}.narrow{max-width:760px}
  .eyebrow{font:500 12px/1 var(--sans);letter-spacing:.32em;text-transform:uppercase;color:var(--gold)}
  h1,h2,h3{font-family:var(--serif);font-weight:300;letter-spacing:-.01em;margin:0;line-height:1.08}
  .display{font-size:clamp(38px,5.4vw,66px)}
  em{font-style:italic;color:var(--gold)}
  .btn{display:inline-flex;align-items:center;gap:10px;font:500 14px var(--sans);padding:14px 26px;border-radius:999px;border:1px solid var(--ink);color:#f5f2ea;background:var(--ink);transition:.25s;cursor:pointer}
  .btn:hover{background:transparent;color:var(--ink)}.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}
  header{position:fixed;inset:0 0 auto;z-index:40;transition:.3s}header.solid{background:rgba(245,242,234,.82);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
  .nav{display:flex;align-items:center;justify-content:space-between;height:78px}
  .brand{display:flex;align-items:center;gap:11px;font-family:var(--serif);font-size:26px}
  .nav-links{display:flex;gap:32px;align-items:center;height:100%}.nav-links a{font:500 14px var(--sans);color:var(--mute)}.nav-links a:hover{color:var(--ink)}
  .nav .right{display:flex;gap:20px;align-items:center}.nav .right .si{font:500 14px var(--sans);color:var(--mute)}
  @media(max-width:900px){.nav-links{display:none}}
  .burger{display:none;align-items:center;justify-content:center;width:42px;height:42px;border-radius:11px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer;flex:none;padding:0}
  .burger svg{width:20px;height:20px}
  .mscrim{position:fixed;inset:0;background:rgba(10,10,11,.5);opacity:0;visibility:hidden;transition:opacity .3s;z-index:55}.mscrim.show{opacity:1;visibility:visible}
  .mdrawer{position:fixed;top:0;right:0;bottom:0;width:min(84vw,330px);background:var(--bg);border-left:1px solid var(--line);z-index:60;transform:translateX(100%);transition:transform .32s cubic-bezier(.2,.7,.2,1);display:flex;flex-direction:column;padding:22px 26px 30px;overflow-y:auto}
  .mdrawer.show{transform:none}
  .mdrawer .mclose{align-self:flex-end;background:none;border:none;color:var(--mute);font-size:28px;line-height:1;cursor:pointer;padding:2px 4px;margin-bottom:6px}
  .mdrawer a{font:500 17px var(--sans);color:var(--ink);padding:14px 0;border-bottom:1px solid var(--line-2)}
  .mdrawer a.msi{color:var(--mute);font-size:15px}
  .mdrawer a.mcta{margin-top:20px;border:none;background:var(--ink);color:var(--bg);text-align:center;border-radius:999px;padding:15px;font-weight:600}
  @media(max-width:900px){.burger{display:inline-flex}}
  /* nav dropdown (.nav-drop/.nav-menu) and the whole footer (.hfoot/.hf-*) come from /static/brand.css */
  /* blog index */
  .bhero{padding:150px 0 30px}
  .bhero .lede{font-size:clamp(18px,2vw,21px);color:var(--mute);max-width:52ch;margin-top:16px}
  .bctl{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin:26px 0 8px;padding-bottom:18px;border-bottom:1px solid var(--line-2)}
  .btags{display:flex;gap:8px;flex-wrap:wrap}
  .btag{font:500 12.5px var(--sans);color:var(--mute);border:1px solid var(--line);padding:6px 13px;border-radius:999px}
  .btag.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
  .bsort a{font:500 13px var(--sans);color:var(--faint);margin-left:14px}.bsort a.on{color:var(--ink);text-decoration:underline}
  .bgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:30px;padding:34px 0}
  @media(max-width:900px){.bgrid{grid-template-columns:1fr}}
  .bcard{display:flex;flex-direction:column;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--bg-2);transition:.25s}
  .bcard:hover{transform:translateY(-3px);border-color:var(--gold)}
  .bcard .cover{aspect-ratio:16/10;object-fit:cover;width:100%;display:block;background:#e7e0d2}
  .bcard .bc-in{padding:20px 22px 24px;display:flex;flex-direction:column;gap:10px;flex:1}
  .bcard .bc-meta{font:500 11.5px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
  .bcard h3{font-size:24px}
  .bcard .bc-dek{color:var(--mute);font-size:14.5px;flex:1}
  .bcard .bc-more{font:500 13px var(--sans);color:var(--gold)}
  .pager{display:flex;align-items:center;justify-content:center;gap:8px;padding:20px 0 10px}
  .pager a,.pager span{font:500 13px var(--sans);min-width:38px;height:38px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:10px;color:var(--mute)}
  .pager a:hover{border-color:var(--ink);color:var(--ink)}.pager .on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
  .pager .off{opacity:.4}
  .bempty{padding:60px 0;color:var(--faint)}
  /* article */
  .art{padding:140px 0 10px}
  .art .crumb{font:500 13px var(--sans);color:var(--faint);margin-bottom:20px}
  .art .crumb a:hover{color:var(--ink)}
  .art h1{font-size:clamp(32px,4.6vw,54px);max-width:20ch}
  .art .byline{display:flex;gap:12px;flex-wrap:wrap;color:var(--faint);font:500 13.5px var(--sans);margin:20px 0 6px}
  .art .dek{font-size:clamp(18px,2vw,22px);color:var(--mute);max-width:56ch;margin-top:10px;font-family:var(--serif);font-style:italic}
  .art .cover{width:100%;aspect-ratio:16/8;object-fit:cover;border-radius:16px;margin:34px 0 10px;background:#e7e0d2}
  .prose{max-width:720px;margin:30px auto 0;font-size:17.5px;line-height:1.72;color:#2b2820}
  .prose h2{font-size:clamp(26px,3vw,34px);margin:44px 0 14px}
  .prose h3{font-size:22px;margin:32px 0 10px}
  .prose p{margin:0 0 20px}.prose ul,.prose ol{margin:0 0 20px;padding-left:22px}.prose li{margin:6px 0}
  .prose a{color:var(--gold);text-decoration:underline}
  .prose img{max-width:100%;border-radius:12px;margin:14px 0}
  .prose blockquote{margin:26px 0;padding:6px 0 6px 22px;border-left:2px solid var(--gold);font-family:var(--serif);font-style:italic;font-size:22px;color:var(--ink)}
  .prose strong{font-weight:600;color:var(--ink)}
  .cmp-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:14px;margin:28px 0}
  table.cmp{width:100%;border-collapse:collapse;font-size:14.5px;min-width:620px}
  table.cmp th,table.cmp td{padding:13px 16px;text-align:left;border-top:1px solid var(--line-2);vertical-align:top}
  table.cmp thead th{background:var(--bg-2);border-top:none;font:600 11px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
  table.cmp thead th.h{color:var(--ink)}
  table.cmp td.row{font-weight:600;color:var(--ink);white-space:nowrap}
  table.cmp td.us{background:rgba(122,115,99,.09);color:var(--ink)}
  .cmp-src{font-size:12.5px;color:var(--faint);margin-top:-14px}
  .arts-cta{text-align:center}.pad{padding:clamp(70px,10vh,120px) 0}
  .tagrow{display:flex;gap:8px;flex-wrap:wrap;max-width:720px;margin:30px auto 0}
"""


def _origin() -> str:
    import os
    return os.environ.get("HALIA_SITE_URL", "https://haliascore.com").rstrip("/")


def _abs_url(path_or_url: str) -> str:
    if not path_or_url:
        return ""
    if path_or_url.startswith("http"):
        return path_or_url
    return _origin() + ("" if path_or_url.startswith("/") else "/") + path_or_url


def _social_head(title: str, desc: str, *, canonical: str = "", og_type: str = "website",
                 image: str = "") -> str:
    """Canonical + Open Graph + Twitter tags for a blog page. `canonical` is a path (e.g. /blog)."""
    e = _html.escape
    url = _abs_url(canonical) if canonical else ""
    img = _abs_url(image) if image else f"{_origin()}/img/three_clients.jpg"
    tags = []
    if url:
        tags.append(f'<link rel="canonical" href="{e(url)}">')
        tags.append(f'<meta property="og:url" content="{e(url)}">')
    tags += [
        '<meta property="og:site_name" content="Halia">',
        f'<meta property="og:type" content="{e(og_type)}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:image" content="{e(img)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">',
        f'<meta name="twitter:description" content="{e(desc)}">',
        f'<meta name="twitter:image" content="{e(img)}">',
    ]
    return "".join(tags)


def _breadcrumb(items: list) -> dict:
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": name, "item": _abs_url(path)}
        for i, (name, path) in enumerate(items)]}


def _index_jsonld() -> str:
    from halia.api.content import jsonld_script, org_graph
    o = _origin()
    graph = org_graph() + [
        {"@type": "Blog", "@id": f"{o}/blog#blog", "name": "The Halia Journal",
         "url": f"{o}/blog", "inLanguage": "en",
         "description": "Field notes and comparisons on private client intelligence for luxury retail.",
         "publisher": {"@id": f"{o}/#organization"}},
        _breadcrumb([("Home", "/"), ("Journal", "/blog")]),
    ]
    return jsonld_script(graph)


def _post_jsonld(post: dict, canonical: str, desc: str, image: str) -> str:
    from halia.api.content import jsonld_script, org_graph
    o = _origin()
    url = _abs_url(canonical)
    author = post.get("author") or "Halia"
    author_type = "Organization" if "team" in author.lower() or author == "Halia" else "Person"
    published = post.get("published_at") or ""
    node = {
        "@type": "BlogPosting",
        "@id": f"{url}#post",
        "headline": (post.get("title") or "")[:110],
        "description": desc,
        "url": url,
        "mainEntityOfPage": {"@id": url},
        "author": {"@type": author_type, "name": author},
        "publisher": {"@id": f"{o}/#organization"},
        "isPartOf": {"@id": f"{o}/blog#blog"},
        "inLanguage": "en",
    }
    if published:
        node["datePublished"] = published
        node["dateModified"] = post.get("updated_at") or published
    if image:
        node["image"] = _abs_url(image)
    if _tags(post):
        node["keywords"] = ", ".join(_tags(post))
    graph = org_graph() + [
        node,
        _breadcrumb([("Home", "/"), ("Journal", "/blog"), (post.get("title") or "Post", canonical)]),
    ]
    return jsonld_script(graph)


def _doc(title: str, meta_desc: str, body: str, *, index: bool = True, extra_head: str = "",
         canonical: str = "", og_type: str = "website", image: str = "", jsonld: str = "") -> str:
    robots = "" if index else '<meta name="robots" content="noindex, nofollow">'
    social = _social_head(title, meta_desc, canonical=canonical, og_type=og_type, image=image) if index else ""
    return (
        "<!doctype html><html lang=\"en\"><head>"
        "<link rel=\"stylesheet\" href=\"/static/brand.css\"><script src=\"/static/brand.js\" defer></script>"
        f"<link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%237a7363'>{_ASTER}</text></svg>\">"
        "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"{robots}<title>{_html.escape(title)}</title>"
        f"<meta name=\"description\" content=\"{_html.escape(meta_desc)}\">"
        f"{social}"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
        "<link href=\"https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter:wght@400;500&display=swap\" rel=\"stylesheet\">"
        f"<style>{_BLOG_CSS}</style>{jsonld}{extra_head}</head><body>"
        f"{_nav()}{body}{_footer()}{_SCRIPT}{_chat()}</body></html>"
    )


def _chat() -> str:
    from halia.api.content import analytics_snippet, chat_widget_snippet
    return chat_widget_snippet() + analytics_snippet()


# ── public rendering ───────────────────────────────────────────────────────────────
def _card(post: dict) -> str:
    cover = (f'<img class="cover" src="/blog/img/{_html.escape(post["cover_image_id"])}" '
             f'alt="" loading="lazy">' if post.get("cover_image_id") else "")
    meta = _html.escape(" · ".join(x for x in (post.get("author"),
                        _date_label(post.get("published_at") or post.get("updated_at")),
                        f"{_read_min(post.get('body_html',''))} min read") if x))
    return (
        f'<a class="bcard" href="/blog/{_html.escape(post["slug"])}">{cover}'
        f'<div class="bc-in"><div class="bc-meta">{meta}</div>'
        f'<h3>{_html.escape(post.get("title") or "Untitled")}</h3>'
        f'<div class="bc-dek">{_html.escape(post.get("dek") or "")}</div>'
        f'<div class="bc-more">Read &rarr;</div></div></a>')


def _pager(page: int, pages: int, sort: str, tag: str | None) -> str:
    if pages <= 1:
        return ""
    qs = lambda p: (f"?page={p}" + (f"&sort={sort}" if sort != "newest" else "")
                    + (f"&tag={tag}" if tag else ""))
    out = []
    out.append(f'<a href="{qs(page-1)}">&lsaquo;</a>' if page > 1 else '<span class="off">&lsaquo;</span>')
    for p in range(1, pages + 1):
        out.append(f'<span class="on">{p}</span>' if p == page else f'<a href="{qs(p)}">{p}</a>')
    out.append(f'<a href="{qs(page+1)}">&rsaquo;</a>' if page < pages else '<span class="off">&rsaquo;</span>')
    return f'<div class="pager">{"".join(out)}</div>'


def _all_tags(store) -> list[str]:
    seen: list[str] = []
    for p in store.list_posts(published_only=True, limit=200, offset=0):
        for t in _tags(p):
            if t not in seen:
                seen.append(t)
    return seen


def render_index(store, page: int, sort: str, tag: str | None) -> str:
    total = store.count_posts(published_only=True, tag=tag)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, pages))
    posts = store.list_posts(published_only=True, sort=sort, tag=tag,
                             limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    cards = "".join(_card(p) for p in posts) or (
        '<div class="bempty">No posts yet. Check back soon.</div>')
    tqs = lambda t: ("/blog" + (f"?tag={t}" if t else "") + (("&" if t else "?") + f"sort={sort}" if sort != "newest" else ""))
    all_chip = f'<a class="btag{"" if tag else " on"}" href="{tqs("")}">All</a>'
    other_chips = "".join(
        f'<a class="btag{" on" if (tag or "")==t else ""}" href="{tqs(t)}">{_html.escape(t)}</a>'
        for t in _all_tags(store))
    sort_ctl = (f'<div class="bsort">Sort '
                f'<a class="{"on" if sort!="oldest" else ""}" href="/blog{("?tag="+tag) if tag else ""}">Newest</a>'
                f'<a class="{"on" if sort=="oldest" else ""}" href="/blog?sort=oldest{("&tag="+tag) if tag else ""}">Oldest</a></div>')
    body = (
        '<section class="bhero"><div class="wrap">'
        '<div class="eyebrow">The Halia Journal</div>'
        '<h1 class="display">Notes on private client intelligence.</h1>'
        '<p class="lede">Field notes, comparisons, and thinking on how luxury retailers find and keep '
        'the high-value clients hiding in their own data.</p>'
        f'<div class="bctl"><div class="btags">{all_chip}{other_chips}</div>{sort_ctl}</div>'
        f'<div class="bgrid">{cards}</div>'
        f'{_pager(page, pages, sort, tag)}'
        '</div></section>')
    return _doc("The Halia Journal", "Field notes and comparisons on private client "
                "intelligence for luxury retail.", body,
                canonical="/blog", og_type="website", jsonld=_index_jsonld())


def render_post(post: dict, *, preview: bool = False) -> str:
    cover = (f'<img class="cover" src="/blog/img/{_html.escape(post["cover_image_id"])}" alt="">'
             if post.get("cover_image_id") else "")
    byline = " · ".join(x for x in (
        _html.escape(post.get("author") or ""),
        f'<time datetime="{_html.escape(post.get("published_at") or "")}">'
        f'{_html.escape(_date_label(post.get("published_at") or post.get("updated_at")))}</time>',
        f"{_read_min(post.get('body_html',''))} min read") if x)
    tags = "".join(f'<span class="btag">{_html.escape(t)}</span>' for t in _tags(post))
    draft_note = ('<div class="crumb" style="color:#b4632b">Draft preview — not visible to the '
                  'public.</div>' if preview else "")
    body = (
        '<article class="art"><div class="wrap narrow">'
        f'{draft_note}'
        '<div class="crumb"><a href="/blog">&larr; The Journal</a></div>'
        '<div class="eyebrow">Journal</div>'
        f'<h1>{_html.escape(post.get("title") or "Untitled")}</h1>'
        f'<div class="byline">{byline}</div>'
        f'<p class="dek">{_html.escape(post.get("dek") or "")}</p>'
        f'{cover}</div>'
        f'<div class="prose">{_sanitize(post.get("body_html") or "")}</div>'
        f'{(f"<div class=tagrow>{tags}</div>") if tags else ""}'
        '</article>'
        '<section class="pad arts-cta"><div class="wrap">'
        '<div class="eyebrow" style="margin-bottom:20px">Begin</div>'
        '<h2 class="display" style="font-size:clamp(30px,4vw,46px)">See who you have been missing.</h2>'
        '<p class="lede" style="max-width:40ch;margin:14px auto 30px;color:var(--mute)">Connect your '
        'store and Halia surfaces your hidden VICs, usually within the hour.</p>'
        '<a class="btn" href="/connect">Connect your store <span class="arrow">&rarr;</span></a>'
        '</div></section>')
    slug = post.get("slug") or ""
    canonical = f"/blog/{slug}"
    desc = post.get("dek") or (
        f"{post.get('title') or 'From the Halia Journal'} — notes on private client "
        "intelligence for luxury retail, from Halia.")
    image = f"/blog/img/{post['cover_image_id']}" if post.get("cover_image_id") else ""
    jsonld = "" if preview else _post_jsonld(post, canonical, desc, image)
    return _doc(f"{post.get('title')} · Halia Journal", desc, body, index=not preview,
                canonical=canonical, og_type="article", image=image, jsonld=jsonld)


# ── admin authoring ────────────────────────────────────────────────────────────────
_QUILL_HEAD = (
    '<link href="https://cdn.jsdelivr.net/npm/quill@2/dist/quill.snow.css" rel="stylesheet">'
    '<script src="https://cdn.jsdelivr.net/npm/quill@2/dist/quill.js"></script>')


def _admin_list(request: Request) -> str:
    store = shop_store()
    posts = store.list_posts(published_only=False, sort="newest", limit=200, offset=0)
    rows = []
    for p in posts:
        badge = ('<span style="color:#0f7b4f">● Published</span>' if p.get("status") == "published"
                 else '<span style="color:#b4632b">○ Draft</span>')
        when = _html.escape(_date_label(p.get("published_at") or p.get("updated_at")))
        rows.append(
            f'<tr><td style="padding:11px 12px"><b>{_html.escape(p.get("title") or "Untitled")}</b>'
            f'<div style="color:#8a8a8a;font-size:12.5px">/{_html.escape(p.get("slug"))}</div></td>'
            f'<td style="padding:11px 12px;font-size:13px">{badge}</td>'
            f'<td style="padding:11px 12px;font-size:13px;color:#616161">{when}</td>'
            f'<td style="padding:11px 12px;text-align:right;white-space:nowrap">'
            f'<a class="btn ghost" style="padding:6px 12px" href="/blog/{_html.escape(p.get("slug"))}" target="_blank">View</a> '
            f'<a class="btn ghost" style="padding:6px 12px" href="/admin/blog/edit/{_html.escape(p.get("slug"))}">Edit</a> '
            f'<form method="post" action="/admin/blog/delete" style="display:inline" '
            f'onsubmit="return confirm(\'Delete this post?\')">'
            f'<input type="hidden" name="slug" value="{_html.escape(p.get("slug"))}">'
            f'<button class="btn ghost" style="padding:6px 12px;color:#8e1f0b" type="submit">Delete</button></form></td></tr>')
    table = (
        '<table style="width:100%;border-collapse:collapse;border:1px solid #e3e3e3;border-radius:12px;overflow:hidden">'
        '<thead><tr style="background:#fafafa;color:#616161;font:600 11px system-ui;letter-spacing:.06em;text-transform:uppercase">'
        '<th style="text-align:left;padding:10px 12px">Post</th><th style="text-align:left;padding:10px 12px">Status</th>'
        '<th style="text-align:left;padding:10px 12px">Date</th><th></th></tr></thead>'
        f'<tbody>{"".join(rows) if rows else "<tr><td style=padding:16px colspan=4>No posts yet.</td></tr>"}</tbody></table>')
    actions = "<a class='btn' href='/admin/blog/new'>New post</a>"
    return console._shell("blog", "Blog", table, subtitle="Write and publish posts", actions=actions)


def _admin_editor(request: Request, post: dict | None) -> str:
    p = post or {"slug": "", "title": "", "dek": "", "body_html": "", "author": "The Halia team",
                 "tags": "", "status": "draft", "cover_image_id": ""}
    is_new = post is None
    cover = p.get("cover_image_id") or ""
    cover_prev = (f'<img id="coverPrev" src="/blog/img/{_html.escape(cover)}" '
                  f'style="max-width:220px;border-radius:10px;display:block;margin-top:8px">'
                  if cover else '<img id="coverPrev" style="max-width:220px;border-radius:10px;display:none;margin-top:8px">')
    I = "box-sizing:border-box;width:100%;padding:10px 12px;border:1px solid #d8d8d8;border-radius:10px;font:14px system-ui;margin-top:6px"
    L = "font:600 12px system-ui;color:#616161;letter-spacing:.02em;display:block;margin-top:16px"
    form = f"""
    {_QUILL_HEAD}
    <form method="post" action="/admin/blog/save" id="postForm" style="max-width:820px">
      <input type="hidden" name="orig_slug" value="{_html.escape(p.get('slug') or '')}">
      <input type="hidden" name="body_html" id="bodyHtml">
      <input type="hidden" name="cover_image_id" id="coverId" value="{_html.escape(cover)}">
      <label style="{L};margin-top:0">Title
        <input style="{I}" name="title" id="title" value="{_html.escape(p.get('title') or '')}" placeholder="Post title" required></label>
      <label style="{L}">URL slug <span style="color:#9a9a9a;font-weight:500">(auto from title; edit if you like)</span>
        <input style="{I}" name="slug" id="slug" value="{_html.escape(p.get('slug') or '')}" placeholder="my-post"></label>
      <label style="{L}">Excerpt (dek)
        <input style="{I}" name="dek" value="{_html.escape(p.get('dek') or '')}" placeholder="One-line summary shown on cards"></label>
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <label style="{L};flex:1;min-width:200px">Author
          <input style="{I}" name="author" value="{_html.escape(p.get('author') or '')}"></label>
        <label style="{L};flex:1;min-width:200px">Tags <span style="color:#9a9a9a;font-weight:500">(comma-separated)</span>
          <input style="{I}" name="tags" value="{_html.escape(p.get('tags') or '')}" placeholder="comparison, luxury"></label>
      </div>
      <label style="{L}">Cover image
        <input type="file" accept="image/*" id="coverFile" style="margin-top:6px;display:block">{cover_prev}</label>
      <label style="{L}">Body</label>
      <div id="editor" style="background:#fff;border-radius:10px;margin-top:6px;min-height:360px"></div>
      <div style="display:flex;gap:16px;align-items:center;margin-top:18px">
        <label style="font:600 13px system-ui;color:#303030;display:flex;align-items:center;gap:8px">
          <input type="checkbox" name="published" id="published" {"checked" if p.get("status")=="published" else ""}> Published</label>
        <div style="flex:1"></div>
        <a class="btn ghost" href="/admin/blog">Cancel</a>
        <button class="btn" type="submit" id="saveBtn">Save post</button>
      </div>
    </form>"""
    # Script kept as a plain (non-f) string so JS braces need no escaping; two values injected below.
    script = _EDITOR_JS.replace("__INITIAL__", _json(p.get("body_html") or "")) \
                       .replace("__ISNEW__", "true" if is_new else "false")
    title = "New post" if is_new else "Edit post"
    return console._shell("blog", title, form + script, subtitle="Write and publish")


_EDITOR_JS = """
<script>
(function(){
  var quill = new Quill('#editor', {theme:'snow', modules:{toolbar:[
    [{header:[2,3,false]}],'bold','italic','link','blockquote',
    [{list:'ordered'},{list:'bullet'}],'image','clean']}});
  quill.clipboard.dangerouslyPasteHTML(__INITIAL__);
  quill.getModule('toolbar').addHandler('image', function(){
    var input=document.createElement('input');input.type='file';input.accept='image/*';input.click();
    input.onchange=function(){var f=input.files[0];if(!f)return;var fd=new FormData();fd.append('file',f);
      fetch('/admin/blog/image',{method:'POST',body:fd}).then(function(r){return r.json()}).then(function(d){
        if(d.url){var range=quill.getSelection(true);quill.insertEmbed(range.index,'image',d.url);}
        else alert('Upload failed');}).catch(function(){alert('Upload failed');});};
  });
  var t=document.getElementById('title'),s=document.getElementById('slug'),isNew=__ISNEW__;
  function slugify(v){return v.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'');}
  if(isNew){t.addEventListener('input',function(){s.value=slugify(t.value);});}
  var cf=document.getElementById('coverFile'),cp=document.getElementById('coverPrev'),cid=document.getElementById('coverId');
  if(cf)cf.onchange=function(){var f=cf.files[0];if(!f)return;var fd=new FormData();fd.append('file',f);
    fetch('/admin/blog/image',{method:'POST',body:fd}).then(function(r){return r.json()}).then(function(d){
      if(d.id){cid.value=d.id;cp.src=d.url;cp.style.display='block';}});};
  document.getElementById('postForm').addEventListener('submit',function(){
    document.getElementById('bodyHtml').value=quill.root.innerHTML;
    if(!s.value)s.value=slugify(t.value);});
})();
</script>"""


def _json(s: str) -> str:
    import json
    return json.dumps(s)


# ── comparison seed ────────────────────────────────────────────────────────────────
_COMPARISON_BODY = """
<p>Every customer-intelligence tool answers the same question out loud: <em>who is actually buying
from you?</em> But OuterSignal, Mercana, and Halia answer different versions of it, and the version
you choose decides what you can do next.</p>

<h2>Influence, or net worth</h2>
<p>OuterSignal and Mercana are built to surface <strong>influencers and public figures</strong>: the
customer with a large following, the actor, the athlete, the founder with a podcast. That is genuinely
useful. A well-timed gift becomes a story; a story becomes reach; reach is a marketing asset.</p>
<p>Halia is built to surface <strong>high-net-worth private clients</strong>: the quiet buyers whose
spending, once recognised and nurtured, becomes a material share of your revenue. Most of them will
never post about you. They are not a campaign. They are the people who, over a year, place the orders
that move your numbers.</p>
<p>Both are worth finding. They are simply different jobs. A famous name earns you exposure. A wealthy
regular earns you revenue. If your goal is growth on the bottom line rather than a moment on social,
that distinction is the whole game.</p>

<h2>Where the data comes from, and whether it stays</h2>
<p>OuterSignal and Mercana enrich each customer by calling external people-data APIs and then keep the
enriched profiles on file. That depth is real, and so is the trade-off: you are building a retained
store of third-party data about your customers.</p>
<p>Halia works the other way. Every customer is scored in memory, on the spot, from open reference
data held offline, and then released. Nothing about your customers is written to disk or kept. For a
house that sells into the EU, that difference is decisive rather than cosmetic: zero retention is a
posture you can stand behind with a regulator, not a setting.</p>

<h2>Why the pricing works differently</h2>
<p>Because OuterSignal and Mercana pay an external provider for every enrichment, they meter: a
per-unique-customer charge, or a monthly enrichment quota. That is honest cost recovery for their
model.</p>
<p>Halia has no per-customer external cost, so it does not meter. Pricing is a flat monthly figure
banded by the size of your book. Predictable, and aligned with a luxury house that would rather not
watch a counter tick with every order.</p>

<h2>Built for a different shelf</h2>
<p>OuterSignal and Mercana are shaped for high-volume direct-to-consumer brands. Halia is shaped for
luxury and premium retail: it grades every customer from A&#42; to C, estimates the latent value
behind a modest order, and hands your clienteling team a specific move, a private appointment, an
early allocation, a personal note, in the tools they already use.</p>

<div class="cmp-wrap"><table class="cmp">
<thead><tr><th>&nbsp;</th><th class="h">Halia</th><th>OuterSignal</th><th>Mercana</th></tr></thead>
<tbody>
<tr><td class="row">Who it surfaces</td><td class="us">High-net-worth private clients</td><td>Influencers &amp; public figures</td><td>Influencers &amp; public figures</td></tr>
<tr><td class="row">What you do with it</td><td class="us">Grow revenue &amp; lifetime value</td><td>Exposure, gifting, partnerships</td><td>Exposure, gifting, partnerships</td></tr>
<tr><td class="row">How buyers are identified</td><td class="us">Offline wealth signals, scored in memory</td><td>External enrichment APIs</td><td>External enrichment APIs</td></tr>
<tr><td class="row">Customer data retention</td><td class="us">None: scored, then released</td><td>Retained</td><td>Retained</td></tr>
<tr><td class="row">EU / GDPR fit</td><td class="us">Serviceable by architecture</td><td>US-based</td><td>US-based</td></tr>
<tr><td class="row">Pricing model</td><td class="us">Flat monthly, by book size</td><td>Flat + per-unique-customer</td><td>Monthly enrichment quotas</td></tr>
<tr><td class="row">Market focus</td><td class="us">Luxury &amp; premium retail</td><td>Mass-market DTC</td><td>Mass-market DTC</td></tr>
</tbody></table></div>
<p class="cmp-src">Competitor details are drawn from OuterSignal's and Mercana's public pricing and
product pages, current as of writing. Both are capable products; the comparison is about fit, not
merit.</p>

<h2>When each one fits</h2>
<p>If you run a high-volume DTC brand and your next win is an influencer seeding programme or a wave
of gifting, OuterSignal or Mercana will serve you well, and their social enrichment is deep.</p>
<p>If you run a luxury or premium house, sell into the EU, and your growth comes from recognising and
looking after the private clients already in your book, Halia is built for exactly that: find the
high-net-worth buyer hiding behind a modest first order, and make the move that turns them into a
client for years.</p>
"""


# ── Altrata (Salesforce app) seed ────────────────────────────────────────────────────
_ALTRATA_BODY = """
<p>Altrata has put its data into Salesforce. Wealth-X, WealthEngine, BoardEx, and RelSci, the
datasets behind much of the wealth-screening world, now arrive as one standardised feed inside the
CRM, matched to your records and refreshed automatically. It is a serious piece of infrastructure.
It also answers a different question from the one a luxury house asks at the counter.</p>

<h2>Relationship intelligence, or a buyer in your book</h2>
<p>Altrata is built for reaching <strong>executives and organisations</strong>: the board member to
warm up before a raise, the C-suite name behind an account, the decision-maker a search firm needs to
place. Its heritage is dealmaking, fundraising, executive search, and account-based marketing, work
where knowing who sits where, and who knows whom, is the whole advantage.</p>
<p>Halia is built for a quieter figure: the <strong>high-net-worth private client already buying from
you</strong>. Not a prospect to source from a database, but the person who placed a modest first order
last week and, once recognised and looked after, becomes a material share of your year. Altrata helps
you find someone out in the world and open a door. Halia helps you notice someone already inside it.</p>
<p>Both are real jobs, and they rarely overlap. A wealth-screening feed points a sales or development
team at named individuals to pursue. A clienteling engine tells a boutique which of today's buyers
deserves a personal note this afternoon.</p>

<h2>Where the data lives, and whether it stays</h2>
<p>The Altrata app works by enrichment: it matches your Salesforce contacts and accounts to its
datasets, writes the detail onto the record, and keeps it current with automated updates. The value is
a CRM that stays populated and clean. The trade-off is built into the design: you are accumulating a
retained store of third-party data about individuals, and committing to keep it fresh indefinitely.</p>
<p>Halia is built the other way around. Each customer is scored in memory, in the moment, from open
reference data held offline, and then let go. No enriched profile is written into your systems, and
nothing about a customer is kept once the score is shown. For a house that would rather hold
intelligence than an inventory of personal data, that is the point rather than a footnote.</p>

<h2>Enterprise CRM, or the tools your floor already uses</h2>
<p>Altrata's app assumes Salesforce: an enterprise CRM, a data operation, and a team whose day runs
through it. Halia assumes a shop. It grades every customer from A&#42; to C, estimates the latent value
behind a small order, and hands your clienteling team a specific move inside the tools they already
open, Shopify and the inbox, with no data warehouse to feed.</p>

<h2>What it means in the EU</h2>
<p>Enriching customer records with retained wealth data, and keeping it updated, is a posture that
draws hard questions from a European regulator. Halia's answer is architectural: because it retains
nothing, there is no store to disclose, minimise, or delete on request. Zero retention is a position
you can stand behind, rather than a box you tick.</p>

<div class="cmp-wrap"><table class="cmp">
<thead><tr><th>&nbsp;</th><th class="h">Halia</th><th>Altrata in Salesforce</th></tr></thead>
<tbody>
<tr><td class="row">Who it surfaces</td><td class="us">High-net-worth private clients in your book</td><td>Executives, boards &amp; organisations</td></tr>
<tr><td class="row">What you do with it</td><td class="us">Grow revenue &amp; lifetime value from existing buyers</td><td>Source, verify &amp; connect with named people</td></tr>
<tr><td class="row">How it delivers</td><td class="us">A live score, in memory</td><td>Enriched records inside the CRM</td></tr>
<tr><td class="row">Customer data retention</td><td class="us">None: scored, then released</td><td>Retained &amp; automatically updated</td></tr>
<tr><td class="row">Where it runs</td><td class="us">Shopify &amp; the tools you already use</td><td>Salesforce</td></tr>
<tr><td class="row">EU / GDPR fit</td><td class="us">Serviceable by architecture</td><td>US-based wealth data</td></tr>
<tr><td class="row">Market focus</td><td class="us">Luxury &amp; premium retail</td><td>Dealmaking, fundraising, executive search</td></tr>
</tbody></table></div>
<p class="cmp-src">Altrata product details are drawn from Altrata's public Salesforce-app and product
pages, current as of writing. Altrata is a substantial, capable platform; the comparison is about fit,
not merit.</p>

<h2>When each one fits</h2>
<p>If your next move is a capital raise, an acquisition, a placement, or a programme aimed at named
executives, Altrata's breadth is hard to match, and having it live in Salesforce is a genuine
advantage.</p>
<p>If you run a luxury or premium house and your growth comes from recognising the wealthy buyer hiding
behind a quiet first order, then looking after them for years, Halia is built for exactly that, and it
does the job without keeping a single customer record.</p>
"""


# ── Julius Baer Wealth Report 2026 seed ──────────────────────────────────────────────
_JULIUS_BAER_BODY = """
<p>Julius Baer's 2026 Global Wealth and Lifestyle Report is, on its surface, a story about prices. The
cost of a premium standard of living rose about 10 per cent in US dollar terms over the year, Singapore
held its place at the top, Zurich and Monaco rose to meet it, and London slipped to fifth. Read a
little closer and it is a story about behaviour, and the behaviour it describes is the reason
recognising your best clients has never mattered more.</p>

<h2>Currency, not appetite</h2>
<p>Much of this year's apparent inflation is a currency effect. Cities anchored to a strong franc or
euro climbed the ranking; those tracking the dollar slipped. A Zurich resident barely felt the rise
that pushed their city up the table, while a visitor carrying a weaker currency felt all of it. The
report's own conclusion is that wealth today is global, and its purchasing power depends as much on
where money sits as on what things cost.</p>
<p>For a luxury house, the practical version of that insight is uncomfortable: the price on your shelf
increasingly reflects financial conditions somewhere else. Many luxury brands anchor pricing to the
euro or the franc and hold it level across markets, exporting currency strength into every till. The
client paying it is doing their own arithmetic.</p>

<h2>The buyer who shops across borders</h2>
<p>And they are acting on it. This is the finding that should reshape how retailers think. At least one
in three high-net-worth individuals have already changed the geographic origin of some of their luxury
purchases. More than half would now travel internationally to buy, partly to sidestep tariffs, and
around a quarter already do. In China, buyers are moving toward domestic labels that feel closer to
home.</p>
<p>The affluent consumer, in the report's words, is no longer a passive price-taker. They choose where
to live, where to spend, and where to buy the very same handbag. Their loyalty follows recognition and
relationship rather than postcode. A client who bought from your London store in spring may buy the
identical piece in Singapore in autumn, from whoever remembered them.</p>

<h2>A two-speed floor</h2>
<p>Nor is the spending even. The report describes a two-speed luxury economy: APAC and the Middle East
pulling ahead, Europe contracting hardest, with jewellery and watch spending in Europe down sharply
even as gold-driven prices rose, jewellery up more than 16 per cent and watches more than 15.
Experiences held up everywhere; goods did not. Health spending rose in every region. The wealthy are
still buying, but they are buying deliberately, and differently by region and by mood.</p>
<p>The lesson for a premium retailer, and a European one especially, is that volume will not save the
year. Growth has to come from depth: from knowing the clients already in the book well enough to be
their choice wherever they happen to be standing.</p>

<h2>Which brings it back to the shop floor</h2>
<p>Here is the through-line. The report's wealthy individual is mobile, deliberate, currency-aware, and
quietly enormous, and almost none of that is legible from a single receipt. The modest first order in
your store may belong to a client who spends across three continents and has simply not yet decided you
are worth returning to.</p>
<p>Recognising that person is now the edge. It is a specific act: seeing, from what is already in front
of you, that this quiet buyer is worth a personal appointment, an early allocation, a note that
remembers their last visit. Do that consistently and you become the name they think of in Zurich and in
Singapore alike.</p>
<p>That recognition is the whole job Halia was built for: to find the high-net-worth client hiding
behind an unremarkable order, grade them honestly, and hand your team the move that keeps them. In a
year when the wealthy will happily buy the same thing somewhere else, being the house that knew them is
worth more than being the cheapest counter, which, thanks to the currency, you were never going to be
anyway.</p>

<p class="cmp-src">Figures cited are from the Julius Baer Global Wealth and Lifestyle Report 2026. The
reading, and any opinions, are our own.</p>
"""


# ── Knight Frank Wealth Report 2025 seed ─────────────────────────────────────────────
_KNIGHT_FRANK_BODY = """
<p>Knight Frank's Wealth Report is now in its 19th edition, and though it is written for people who buy
prime property and private jets, its picture of where wealth sits and how it behaves is one of the most
useful maps a luxury retailer can read. This year's edition describes a wealthy population that is
growing, spreading, moving, and changing hands, and every one of those verbs matters at the counter.</p>

<h2>More wealthy people, in more places</h2>
<p>The number of individuals worth US$10 million or more rose 4.4 per cent last year, and those worth
US$100 million passed 100,000 for the first time. The United States still dominates, home to nearly 40
per cent of the world's wealthy and leading in new wealth creation. But the growth is broadening: India
now ranks fourth by HNWI population, the Middle East holds an outsized share of the very wealthiest, and
Knight Frank expects Africa to outperform in the years ahead.</p>
<p>For a luxury house, the useful part is not the league table. It is that your next great client is
less predictable by nationality than ever. Wealth is being made in more industries and more countries,
which means it walks through your door under more names than it used to.</p>

<h2>Wealth that moves</h2>
<p>The report's loudest theme is mobility. The wealthy relocate, hold several homes, and move capital
between jurisdictions with growing ease, supercharging markets from Miami to Dubai, where a US$1 million
prime property in 2020 had become US$1.9 million and US$2.7 million respectively by 2025. Governments
are competing to attract this mobile wealth and, in places, to tax it.</p>
<p>A mobile client is not a postcode. The person who bought from your London boutique in spring may
spend the autumn in Singapore and the winter in Dubai. What holds that relationship together is being
remembered. The house that recognises them wherever they appear keeps the relationship; the one that
treats every visit as a stranger's first tends to lose it.</p>

<h2>The next generation is already here</h2>
<p>Underneath the numbers is a generational handover. Knight Frank's Next Generation Survey of wealthy
18- to 35-year-olds finds a cohort that works remotely and globally, prizes experiences and health over
possessions, and researches online long before it commits. When they do buy a luxury asset, real estate
leads their wish list, but the way they arrive at any purchase is relationship-led and information-rich.
They expect the brands they favour to know them.</p>
<p>As the great wealth transfer accelerates, these are the clients whose loyalty is worth securing
early. They will inherit the accounts that matter, and they will give them to the houses that treated
them as clients before they had to.</p>

<h2>Which brings it back to the counter</h2>
<p>Property, jets, and vineyards are the report's subject, but its through-line belongs to retail too:
wealth is larger, more global, more mobile, and younger than the person in front of you appears. A quiet
first order can belong to an ultra-high-net-worth individual, a mobile professional on their way into
the millions, or the heir to a fortune deciding which brands to keep.</p>
<p>None of that is legible from a receipt. Reading it is the work. Halia was built to find the wealth
signals already present in your own customer data, grade the person honestly, estimate the latent value
behind a modest order, and hand your team the move that turns a passing buyer into a client for the next
decade, wherever in the world they happen to spend it.</p>

<p class="cmp-src">Figures cited are from the Knight Frank Wealth Report 2025 (19th edition). The
reading, and any opinions, are our own.</p>
"""


# House Journal seed posts, in publish order. Dates are held one week apart on purpose;
# seed_blog() reconciles them so the spacing survives even for posts already published.
_SEED_POSTS = [
    {"slug": COMPARISON_SLUG, "published_at": "2026-06-28T09:00:00+00:00",
     "title": "Influence, or net worth: how Halia compares to OuterSignal and Mercana",
     "dek": "All three find VIPs. The difference is which ones, and whether they grow your "
            "revenue or your reach.",
     "body": _COMPARISON_BODY, "tags": "comparison, luxury, positioning"},
    {"slug": ALTRATA_SLUG, "published_at": "2026-07-05T09:00:00+00:00",
     "title": "Stored, or scored: how Halia compares to Altrata's Salesforce app",
     "dek": "Altrata pours executive and wealth data into your CRM and keeps it current. "
            "Halia scores your buyers in memory and keeps nothing. Which you want depends "
            "on the job.",
     "body": _ALTRATA_BODY, "tags": "comparison, wealth data, positioning"},
    {"slug": JULIUS_BAER_SLUG, "published_at": "2026-07-12T09:00:00+00:00",
     "title": "The quiet buyer just got harder to read: on the Julius Baer Wealth Report 2026",
     "dek": "The 2026 Global Wealth and Lifestyle Report says the affluent buyer is now "
            "mobile, deliberate, and spending across borders. That is exactly the client "
            "luxury retail keeps missing.",
     "body": _JULIUS_BAER_BODY, "tags": "wealth, luxury, research"},
    {"slug": KNIGHT_FRANK_SLUG, "published_at": "2026-07-19T09:00:00+00:00",
     "title": "Wealth is moving, and getting younger: reading the Knight Frank Wealth Report 2025",
     "dek": "Knight Frank's 19th Wealth Report finds affluence expanding, globalising, mobile, "
            "and passing to a next generation that buys on relationship. For luxury retail, that "
            "raises the value of simply knowing who your quiet clients are.",
     "body": _KNIGHT_FRANK_BODY, "tags": "wealth, luxury, research"},
]


def seed_blog() -> None:
    """Publish the seed posts, and keep their publish dates one week apart.

    New posts are created; posts already present are left untouched except for their
    ``published_at``, which is reconciled to the canonical one-week-apart schedule so the
    spacing holds even after earlier seeds. Body edits made in the CMS are preserved."""
    store = shop_store()
    for spec in _SEED_POSTS:
        existing = store.get_post(spec["slug"])
        if existing is None:
            store.upsert_post({
                "slug": spec["slug"], "title": spec["title"], "dek": spec["dek"],
                "body_html": _sanitize(spec["body"]), "author": "The Halia team",
                "cover_image_id": None, "tags": spec["tags"], "status": "published",
                "published_at": spec["published_at"],
            })
        elif existing.get("published_at") != spec["published_at"]:
            existing["published_at"] = spec["published_at"]     # fix spacing, keep any edits
            store.upsert_post(existing)


# ── routes ─────────────────────────────────────────────────────────────────────────
def register(app) -> None:
    try:
        seed_blog()
    except Exception:  # noqa: BLE001 — a seed hiccup must never stop the app booting
        pass

    @app.get("/blog", response_class=HTMLResponse)
    def blog_index(request: Request):
        try:
            page = max(1, int(request.query_params.get("page", "1")))
        except ValueError:
            page = 1
        sort = "oldest" if request.query_params.get("sort") == "oldest" else "newest"
        tag = request.query_params.get("tag") or None
        return HTMLResponse(render_index(shop_store(), page, sort, tag))

    @app.get("/blog/img/{image_id}")
    def blog_image(image_id: str):
        img = shop_store().get_image(image_id)
        if not img:
            raise HTTPException(404, "Not found")
        return Response(content=img["data"], media_type=img["mime"] or "application/octet-stream",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/blog/{slug}", response_class=HTMLResponse)
    def blog_post(slug: str, request: Request):
        post = shop_store().get_post(slug)
        if not post:
            raise HTTPException(404, "Post not found")
        if post.get("status") != "published":
            if not _admin_ok(request):           # drafts: visible only to a signed-in admin
                raise HTTPException(404, "Post not found")
            return HTMLResponse(render_post(post, preview=True))
        return HTMLResponse(render_post(post))

    # ── admin ──
    @app.get("/admin/blog", response_class=HTMLResponse)
    def admin_blog(request: Request):
        from halia import config
        if not config.ADMIN_KEY or not _admin_ok(request):
            return RedirectResponse("/admin", status_code=303)
        return HTMLResponse(_admin_list(request))

    @app.get("/admin/blog/new", response_class=HTMLResponse)
    def admin_blog_new(request: Request):
        from halia import config
        if not config.ADMIN_KEY or not _admin_ok(request):
            return RedirectResponse("/admin", status_code=303)
        return HTMLResponse(_admin_editor(request, None))

    @app.get("/admin/blog/edit/{slug}", response_class=HTMLResponse)
    def admin_blog_edit(slug: str, request: Request):
        from halia import config
        if not config.ADMIN_KEY or not _admin_ok(request):
            return RedirectResponse("/admin", status_code=303)
        post = shop_store().get_post(slug)
        if not post:
            raise HTTPException(404, "Post not found")
        return HTMLResponse(_admin_editor(request, post))

    @app.post("/admin/blog/save")
    async def admin_blog_save(request: Request):
        if not _admin_ok(request):
            raise HTTPException(403, "Not signed in.")
        form = await request.form()
        store = shop_store()
        orig = (form.get("orig_slug") or "").strip()
        title = (form.get("title") or "").strip() or "Untitled"
        slug = _slugify((form.get("slug") or "").strip() or title)
        published = bool(form.get("published"))
        existing = store.get_post(orig) if orig else None
        # keep the first publish date; stamp it the moment a post first goes live
        published_at = (existing or {}).get("published_at")
        if published and not published_at:
            from halia.store import _now
            published_at = _now()
        post = {
            "slug": slug,
            "title": title,
            "dek": (form.get("dek") or "").strip(),
            "body_html": _sanitize(str(form.get("body_html") or "")),
            "author": (form.get("author") or "").strip() or "The Halia team",
            "cover_image_id": (form.get("cover_image_id") or "").strip() or None,
            "tags": (form.get("tags") or "").strip(),
            "status": "published" if published else "draft",
            "published_at": published_at,
            "created_at": (existing or {}).get("created_at"),
        }
        # a slug rename: drop the old row
        if orig and orig != slug and existing:
            store.delete_post(orig)
        store.upsert_post(post)
        return RedirectResponse("/admin/blog", status_code=303)

    @app.post("/admin/blog/delete")
    async def admin_blog_delete(request: Request, slug: str = Form(...)):
        if not _admin_ok(request):
            raise HTTPException(403, "Not signed in.")
        shop_store().delete_post(slug)
        return RedirectResponse("/admin/blog", status_code=303)

    @app.post("/admin/blog/image")
    async def admin_blog_image(request: Request, file: UploadFile):
        if not _admin_ok(request):
            raise HTTPException(403, "Not signed in.")
        data = await file.read()
        if len(data) > 6 * 1024 * 1024:
            raise HTTPException(413, "Image too large (max 6MB).")
        image_id = secrets.token_urlsafe(12)
        shop_store().save_image(data, file.content_type or "image/jpeg", image_id)
        return JSONResponse({"id": image_id, "url": f"/blog/img/{image_id}"})
