"""Mini-CMS: edit marketing copy without touching code.

Editable text is wrapped inline in the page HTML with comment delimiters:

    <h1 class="display"><!--cms:home.hero.title-->Your <em>headline</em><!--/cms--></h1>

The text between the markers is the default (what ships in git and renders if nothing is set).
An operator can override any block at /admin; the override is stored in the `content` table and
injected at serve time by apply_overrides(), which the homepage and _serve_page() run through.
Nothing here is customer data — it is website copy.

/admin is gated by HALIA_ADMIN_KEY (unset -> the editor is disabled).
"""
from __future__ import annotations

import hashlib
import hmac
import html as _html
import re
import time

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from config import ROOT
from halia import config
from halia.api.shopify_auth import shop_store
from halia.api.tenant_auth import _secret

_SITE_DIR = ROOT / "web" / "site"
_ADMIN_COOKIE = "halia_admin"
_BLOCK_RE = re.compile(r"<!--cms:([A-Za-z0-9_.\-]+)-->(.*?)<!--/cms-->", re.S)

# Tiny in-process cache so a marketing page view doesn't hit the DB every time.
_cache: dict = {"at": 0.0, "data": {}}
_TTL = 20.0


def _overrides() -> dict:
    now = time.monotonic()
    if now - _cache["at"] > _TTL or not _cache["at"]:
        try:
            _cache["data"] = shop_store().get_content_all()
        except Exception:  # noqa: BLE001 — the CMS must never break a page
            _cache["data"] = {}
        _cache["at"] = now
    return _cache["data"]


def _bust() -> None:
    _cache["at"] = 0.0


def apply_overrides(html_text: str) -> str:
    """Replace each <!--cms:key-->default<!--/cms--> with its stored override, if any."""
    if "<!--cms:" not in html_text:
        return html_text
    ov = _overrides()
    if not ov:
        return html_text

    def repl(m: re.Match) -> str:
        key = m.group(1)
        val = ov.get(key)
        return f"<!--cms:{key}-->{val}<!--/cms-->" if val is not None else m.group(0)

    return _BLOCK_RE.sub(repl, html_text)


def scan_blocks() -> list[dict]:
    """Every cms block across the site: [{key, default, page}], de-duped by key (first wins)."""
    seen: dict[str, dict] = {}
    for f in sorted(_SITE_DIR.rglob("*.html")):
        try:
            txt = f.read_text(encoding="utf-8")
        except OSError:
            continue
        page = f.relative_to(_SITE_DIR).as_posix()
        for m in _BLOCK_RE.finditer(txt):
            key = m.group(1)
            if key not in seen:
                seen[key] = {"key": key, "default": m.group(2), "page": page}
    return list(seen.values())


# ── admin auth (signed, expiring cookie; no account system needed) ───────────────
def _sign(exp: int) -> str:
    return hmac.new(_secret(), f"admin|{exp}".encode(), hashlib.sha256).hexdigest()


def _make_cookie(ttl: int = 60 * 60 * 12) -> str:
    exp = int(time.time()) + ttl
    return f"{exp}|{_sign(exp)}"


def _admin_ok(request: Request) -> bool:
    if not config.ADMIN_KEY:
        return False
    raw = request.cookies.get(_ADMIN_COOKIE) or ""
    try:
        exp_s, sig = raw.split("|", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    return exp >= int(time.time()) and hmac.compare_digest(sig, _sign(exp))


# ── admin UI ─────────────────────────────────────────────────────────────────────
_CSS = (
    "body{margin:0;background:#f4f1ea;color:#1a1712;font-family:Inter,-apple-system,system-ui,"
    "sans-serif;line-height:1.6}a{color:#1a1712}.wrap{max-width:820px;margin:0 auto;padding:40px 24px 90px}"
    "h1{font-family:'Cormorant Garamond',Georgia,serif;font-weight:300;font-size:40px;margin:0 0 6px}"
    ".sub{color:#6b675e;font-size:14px;margin:0 0 26px}"
    ".bar{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:24px}"
    ".ok{background:#e6f2ea;border:1px solid #b7d9c4;color:#1f6b45;border-radius:10px;padding:11px 14px;font-size:14px;margin-bottom:22px}"
    ".pg{font:600 11px Inter;letter-spacing:.14em;text-transform:uppercase;color:#9a9385;margin:30px 0 10px;border-top:1px solid rgba(20,18,12,.12);padding-top:22px}"
    ".blk{margin:0 0 18px}.blk label{display:block;font:600 12.5px Inter;color:#3a372f;margin-bottom:6px}"
    ".blk .k{color:#9a9385;font-weight:500}"
    "textarea{width:100%;box-sizing:border-box;border:1px solid rgba(20,18,12,.2);border-radius:9px;"
    "padding:11px 13px;font:14px/1.5 ui-monospace,Menlo,monospace;background:#fffdf8;color:#1a1712;resize:vertical;min-height:56px}"
    "textarea:focus{outline:none;border-color:#7a7363}"
    ".btn{display:inline-flex;align-items:center;gap:8px;font:600 14px Inter;padding:12px 22px;border-radius:999px;"
    "border:1px solid #1a1712;background:#1a1712;color:#f4f1ea;cursor:pointer;text-decoration:none}"
    ".btn.ghost{background:transparent;color:#1a1712}"
    ".save{position:sticky;bottom:0;background:linear-gradient(transparent,#f4f1ea 40%);padding:22px 0 6px;margin-top:10px}"
    "input[type=password]{border:1px solid rgba(20,18,12,.2);border-radius:9px;padding:12px 14px;font:15px Inter;min-width:260px}"
)


def _page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{title} · Halia</title>"
        "<meta name=viewport content='width=device-width,initial-scale=1'><meta name=robots content=noindex>"
        "<link rel=preconnect href=https://fonts.googleapis.com>"
        "<link href='https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300&family=Inter:wght@400;500;600&display=swap' rel=stylesheet>"
        f"<style>{_CSS}</style></head><body><div class=wrap>{body}</div></body></html>"
    )


def _login_form(error: str = "") -> str:
    err = f"<p style='color:#8e1f0b;font-size:14px'>{_html.escape(error)}</p>" if error else ""
    return _page("Admin", (
        "<h1>Content editor</h1><p class=sub>Sign in to edit the site copy.</p>"
        f"{err}<form method=post action=/admin/login>"
        "<input type=password name=key placeholder='Admin key' autofocus> "
        "<button class=btn type=submit>Sign in</button></form>"))


def _editor(request: Request) -> str:
    blocks = scan_blocks()
    ov = shop_store().get_content_all()
    saved = "<div class=ok>Saved. Your changes are live.</div>" if request.query_params.get("saved") else ""
    by_page: dict[str, list] = {}
    for b in blocks:
        by_page.setdefault(b["page"], []).append(b)
    rows = []
    for page in sorted(by_page):
        rows.append(f"<div class=pg>{_html.escape(page)}</div>")
        for b in by_page[page]:
            cur = ov.get(b["key"], b["default"])
            lines = min(6, max(2, cur.count("\n") + len(cur) // 70 + 1))
            edited = " · edited" if b["key"] in ov else ""
            rows.append(
                f"<div class=blk><label>{_html.escape(b['key'])}<span class=k>{edited}</span></label>"
                f"<textarea name='blk_{_html.escape(b['key'])}' rows={lines}>{_html.escape(cur)}</textarea></div>")
    body = (
        "<div class=bar><div><h1>Content editor</h1>"
        "<p class=sub>Edit the site copy below. HTML like &lt;em&gt; is allowed. Blank a field or set it "
        "back to the original to revert.</p></div>"
        "<div style='display:flex;gap:10px'><a class='btn ghost' href='/' target=_blank>View site ↗</a>"
        "<a class='btn ghost' href=/admin/logout>Sign out</a></div></div>"
        f"{saved}<form method=post action=/admin/save>{''.join(rows)}"
        "<div class=save><button class=btn type=submit>Save changes</button></div></form>")
    if not blocks:
        body += "<p class=sub>No editable blocks found yet.</p>"
    return _page("Content editor", body)


def register(app) -> None:

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(request: Request):
        if not config.ADMIN_KEY:
            return HTMLResponse(_page("Admin disabled",
                "<h1>Content editor</h1><p class=sub>Set <code>HALIA_ADMIN_KEY</code> in the "
                "environment to enable editing.</p>"))
        if not _admin_ok(request):
            return HTMLResponse(_login_form())
        return HTMLResponse(_editor(request))

    @app.post("/admin/login", response_class=HTMLResponse)
    def admin_login(request: Request, key: str = Form("")):
        if not config.ADMIN_KEY or not hmac.compare_digest(key.strip(), config.ADMIN_KEY):
            return HTMLResponse(_login_form("That key is not right."), status_code=401)
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie(_ADMIN_COOKIE, _make_cookie(), httponly=True,
                        secure=(config.HALIA_APP_URL or "").startswith("https"),
                        samesite="lax", max_age=60 * 60 * 12)
        return resp

    @app.get("/admin/logout")
    def admin_logout():
        resp = RedirectResponse("/admin", status_code=303)
        resp.delete_cookie(_ADMIN_COOKIE)
        return resp

    @app.post("/admin/save")
    async def admin_save(request: Request):
        if not _admin_ok(request):
            raise HTTPException(403, "Not signed in.")
        form = await request.form()
        store = shop_store()
        for b in scan_blocks():
            field = "blk_" + b["key"]
            if field not in form:
                continue
            val = str(form[field])
            if val.strip() == b["default"].strip():
                store.delete_content(b["key"])       # reverted to the original -> drop the override
            else:
                store.set_content(b["key"], val)
        _bust()
        return RedirectResponse("/admin?saved=1", status_code=303)
