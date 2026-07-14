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


def _doc(title: str, meta_desc: str, body: str, *, index: bool = True, extra_head: str = "") -> str:
    robots = "" if index else '<meta name="robots" content="noindex, nofollow">'
    return (
        "<!doctype html><html lang=\"en\"><head>"
        "<link rel=\"stylesheet\" href=\"/static/brand.css\"><script src=\"/static/brand.js\" defer></script>"
        f"<link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%237a7363'>{_ASTER}</text></svg>\">"
        "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"{robots}<title>{_html.escape(title)}</title>"
        f"<meta name=\"description\" content=\"{_html.escape(meta_desc)}\">"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
        "<link href=\"https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter:wght@400;500&display=swap\" rel=\"stylesheet\">"
        f"<style>{_BLOG_CSS}</style>{extra_head}</head><body>"
        f"{_nav()}{body}{_footer()}{_SCRIPT}{_chat()}</body></html>"
    )


def _chat() -> str:
    from halia.api.content import chat_widget_snippet
    return chat_widget_snippet()


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
                "intelligence for luxury retail.", body)


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
    return _doc(f"{post.get('title')} · Halia Journal", post.get("dek") or "",
                body, index=not preview)


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


def seed_blog() -> None:
    """Publish the comparison post if it is not already present (idempotent)."""
    store = shop_store()
    if store.get_post(COMPARISON_SLUG):
        return
    store.upsert_post({
        "slug": COMPARISON_SLUG,
        "title": "Influence, or net worth: how Halia compares to OuterSignal and Mercana",
        "dek": "All three find VIPs. The difference is which ones, and whether they grow your "
               "revenue or your reach.",
        "body_html": _sanitize(_COMPARISON_BODY),
        "author": "The Halia team",
        "cover_image_id": None,
        "tags": "comparison, luxury, positioning",
        "status": "published",
        "published_at": "2026-07-08T09:00:00+00:00",
    })


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
