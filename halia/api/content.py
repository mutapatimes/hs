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
from halia.api import console, staff_auth
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


# Editable content that isn't inline in a marketing page — surfaced in /admin under its own group.
# The featured 1:1 outreach draft the dashboard's Email menu offers as a ready mailto (top option).
# Placeholders filled per client (by the dashboard's fillTemplate): {first_name}, {sender}.
EXTRA_BLOCKS = [
    {"key": "email.draft.subject", "page": "Email draft (1:1 outreach note)",
     "default": "A personal note"},
    {"key": "email.draft.body", "page": "Email draft (1:1 outreach note)",
     "default": ("Dear {first_name},\n\nThank you for being one of our most valued clients. I wanted "
                 "to reach out personally to say we’re always here for you — if there is ever anything "
                 "you’d like us to find, set aside, or arrange, just reply to this note.\n\n"
                 "With warm regards,\n{sender}")},
]


def draft_template() -> dict:
    """The 1:1 email draft (subject + body), override-or-default. Used by the dashboard mailto."""
    ov = _overrides()
    subj = ov.get("email.draft.subject", EXTRA_BLOCKS[0]["default"])
    body = ov.get("email.draft.body", EXTRA_BLOCKS[1]["default"])
    return {"subject": subj, "body": body}


def chat_widget_snippet() -> str:
    """The live-chat widget (Brevo Conversations), rendered bottom-right on marketing pages and
    the hosted dashboard when HALIA_CHAT_WIDGET_ID is set. Brevo's free plan includes one agent
    seat, and the account already sends Halia's email, so support lands in the same inbox.
    Returns "" when unconfigured, so pages ship clean by default."""
    import os
    wid = (os.environ.get("HALIA_CHAT_WIDGET_ID") or "").strip()
    if not wid:
        return ""
    return f"""<script>
  (function(d, w, c) {{
    w.BrevoConversationsID = {_json_str(wid)};
    w[c] = w[c] || function() {{ (w[c].q = w[c].q || []).push(arguments); }};
    var s = d.createElement('script'); s.async = true;
    s.src = 'https://conversations-widget.brevo.com/brevo-conversations.js';
    if (d.head) d.head.appendChild(s);
  }})(document, window, 'BrevoConversations');
</script>"""


def _json_str(v: str) -> str:
    import json as _json
    return _json.dumps(v)


def analytics_snippet() -> str:
    """GoatCounter page analytics for the marketing site, rendered when HALIA_ANALYTICS_CODE is
    set to the account code (e.g. "halia" for halia.goatcounter.com). GoatCounter is free, sets
    no cookies and stores no personal data, so it needs no consent banner — the right fit for a
    zero-retention brand. Marketing pages only; the dashboards never carry analytics.
    Returns "" when unconfigured, so pages ship clean by default."""
    import os
    code = (os.environ.get("HALIA_ANALYTICS_CODE") or "").strip()
    if not code or not re.fullmatch(r"[A-Za-z0-9-]+", code):   # a subdomain label, nothing else
        return ""
    return (f'<script data-goatcounter="https://{code}.goatcounter.com/count" '
            'async src="https://gc.zgo.at/count.js"></script>')


def _before_body(html_text: str, snippet: str) -> str:
    if not snippet or "</body>" not in html_text:
        return html_text
    return html_text.replace("</body>", snippet + "\n</body>", 1)


def with_chat_widget(html_text: str) -> str:
    """Append the chat widget before </body> (no-op when unconfigured or no body tag)."""
    return _before_body(html_text, chat_widget_snippet())


def with_site_scripts(html_text: str) -> str:
    """Marketing-page extras: the support chat bubble + GoatCounter analytics."""
    return _before_body(with_chat_widget(html_text), analytics_snippet())


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
    # Non-page editable content (e.g. the 1:1 email draft) — always shown in /admin.
    for b in EXTRA_BLOCKS:
        seen.setdefault(b["key"], {"key": b["key"], "default": b["default"], "page": b["page"]})
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
    if staff_auth.session_ok(request):        # shared single sign-on (also set by the console)
        return True
    raw = request.cookies.get(_ADMIN_COOKIE) or ""
    try:
        exp_s, sig = raw.split("|", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    return exp >= int(time.time()) and hmac.compare_digest(sig, _sign(exp))


# ── admin UI (rendered inside the shared console shell, so /admin and /console feel like
#    one dashboard: same sidebar nav, same look, one sign-in) ───────────────────────
def _login_form(error: str = "") -> str:
    return console._login_form(error, action="/admin/login", heading="Content editor",
                               intro="Sign in to edit the site copy.")


def _disabled_page() -> str:
    return console._page("Content editor disabled",
        "<div class=authwrap><div class=card><h1 style='font-size:22px;margin:0 0 6px'>"
        "Content editor</h1><p class=sub>Set <code>HALIA_ADMIN_KEY</code> in the environment to "
        "enable editing.</p></div></div>")


def _editor(request: Request) -> str:
    blocks = scan_blocks()
    ov = shop_store().get_content_all()
    saved = "<div class=ok2>Saved. Your changes are live.</div>" if request.query_params.get("saved") else ""
    by_page: dict[str, list] = {}
    for b in blocks:
        by_page.setdefault(b["page"], []).append(b)
    rows = []
    for page in sorted(by_page):
        rows.append(f"<div class=sec>{_html.escape(page)}</div>")
        for b in by_page[page]:
            cur = ov.get(b["key"], b["default"])
            lines = min(8, max(2, cur.count("\n") + len(cur) // 70 + 1))
            edited = " · edited" if b["key"] in ov else ""
            rows.append(
                f"<div class=f><label>{_html.escape(b['key'])}"
                f"<span class=mut style='font-weight:500'>{edited}</span></label>"
                f"<textarea name='blk_{_html.escape(b['key'])}' rows={lines}>{_html.escape(cur)}</textarea></div>")
    body = (
        saved
        + "<p class=sub style='margin:-4px 0 20px'>Edit the site copy below. HTML like &lt;em&gt; is "
        "allowed. Blank a field or set it back to the original to revert.</p>"
        f"<form method=post action=/admin/save>{''.join(rows)}"
        "<div class=save><button class=btn type=submit>Save changes</button></div></form>")
    if not blocks:
        body += "<p class=sub>No editable blocks found yet.</p>"
    actions = "<a class='btn ghost' href='/' target=_blank>View site &#8599;</a>"
    return console._shell("content", "Content editor", body,
                          subtitle="Edit the public site copy", actions=actions)


def register(app) -> None:

    @app.get("/admin", response_class=HTMLResponse)
    def admin_home(request: Request):
        if not config.ADMIN_KEY:
            return HTMLResponse(_disabled_page())
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
        staff_auth.set_session(resp)          # also open the console (one sign-in for both)
        return resp

    @app.get("/admin/logout")
    def admin_logout():
        resp = RedirectResponse("/admin", status_code=303)
        resp.delete_cookie(_ADMIN_COOKIE)
        staff_auth.clear_session(resp)        # signing out here signs out of the console too
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
