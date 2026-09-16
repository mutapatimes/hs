"""Single sign-on for the internal staff surfaces: the Console (/console) and the CMS (/admin).

Both surfaces keep their own enable-key (``CONSOLE_KEY`` / ``ADMIN_KEY``) and their own legacy
per-surface cookie, but a successful sign-in on either now also mints one shared ``halia_session``
cookie that the other accepts — so you log in once and move between them freely. It is signed the
same proven way as the per-surface cookies (HMAC over ``_secret()``), with a distinct ``staff|``
prefix. An unset key still disables that surface entirely, independent of the session.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Request

from halia import config
from halia.api.tenant_auth import _secret

SESSION_COOKIE = "halia_session"
# The per-surface legacy cookies. A sign-out on either surface clears all of these, so one
# sign-out truly signs you out of both.
_LEGACY_COOKIES = ("halia_console", "halia_admin")
_TTL = 60 * 60 * 12


def _sign(exp: int, email: str = "") -> str:
    # The key-holder's session (no email) keeps the original signature, so sessions minted before
    # the team existed stay valid; a team member's session binds their address into the signature.
    msg = f"staff|{exp}" if not email else f"staff|{exp}|{email}"
    return hmac.new(_secret(), msg.encode(), hashlib.sha256).hexdigest()


def make_session(ttl: int = _TTL, email: str = "") -> str:
    exp = int(time.time()) + ttl
    email = (email or "").strip().lower()
    return f"{exp}|{_sign(exp)}" if not email else f"{exp}|{email}|{_sign(exp, email)}"


def _parse(raw: str) -> tuple[int, str] | None:
    """(exp, email) for a valid, unexpired cookie; None otherwise. email is '' for the key-holder."""
    parts = (raw or "").split("|")
    try:
        if len(parts) == 2:
            exp, email, sig = int(parts[0]), "", parts[1]
        elif len(parts) == 3:
            exp, email, sig = int(parts[0]), parts[1], parts[2]
        else:
            return None
    except ValueError:
        return None
    if exp < int(time.time()) or not hmac.compare_digest(sig, _sign(exp, email)):
        return None
    return exp, email


def session_ok(request: Request) -> bool:
    """True if the request carries a valid, unexpired shared staff session (key-holder or team)."""
    return identity(request) is not None


def identity(request: Request) -> dict | None:
    """Who is signed in: {"role": "owner"|"editor", "email", "name"}, or None.

    The key-holder is the owner. A team member's session is only as good as their place on the
    team list: remove them from /console/team and the cookie stops working at once."""
    parsed = _parse(request.cookies.get(SESSION_COOKIE) or "")
    if not parsed:
        return None
    _, email = parsed
    if not email:
        return {"role": "owner", "email": "", "name": ""}
    from halia.api.shopify_auth import shop_store
    ed = shop_store().get_editor(email)
    if not ed:
        return None
    return {"role": ed.get("role") or "editor", "email": email, "name": ed.get("name") or ""}


# The identity for the request being rendered, so the shell can show who is signed in and trim
# the nav for a team member. Set by the surfaces' gate checks; None when nobody is.
import contextvars as _cv  # noqa: E402

current = _cv.ContextVar("halia_staff_identity", default=None)


def note(request: Request) -> dict | None:
    who = identity(request)
    current.set(who)
    return who


def _secure() -> bool:
    return (config.HALIA_APP_URL or "").startswith("https")


def set_session(resp, ttl: int = _TTL, email: str = "") -> None:
    """Attach the shared session cookie to a response (called on any surface's sign-in)."""
    resp.set_cookie(SESSION_COOKIE, make_session(ttl, email), httponly=True, secure=_secure(),
                    samesite="lax", max_age=ttl)


# ── sign-in links for the team ───────────────────────────────────────────────────
_LINK_TTL = 15 * 60


def link_token(email: str, ttl: int = _LINK_TTL) -> str:
    """A signed, short-lived token that signs this address in. Stateless: nothing to store."""
    exp = int(time.time()) + ttl
    email = (email or "").strip().lower()
    sig = hmac.new(_secret(), f"editor-link|{exp}|{email}".encode(), hashlib.sha256).hexdigest()
    return f"{exp}|{email}|{sig}"


def link_email(token: str) -> str | None:
    """The address a valid, unexpired link token signs in, or None."""
    parts = (token or "").split("|")
    if len(parts) != 3:
        return None
    try:
        exp = int(parts[0])
    except ValueError:
        return None
    email = parts[1]
    want = hmac.new(_secret(), f"editor-link|{exp}|{email}".encode(), hashlib.sha256).hexdigest()
    if exp < int(time.time()) or not hmac.compare_digest(parts[2], want):
        return None
    return email


def send_link(email: str) -> bool:
    """Email a team member their sign-in link. False when the address is not on the team or mail
    is not configured; the caller answers the same way either way, so the list cannot be probed."""
    from halia import emails, notify
    from halia.api.shopify_auth import shop_store
    email = (email or "").strip().lower()
    ed = shop_store().get_editor(email) if email else None
    if not ed or not notify.email_configured():
        return False
    base = (config.HALIA_APP_URL or "").rstrip("/")
    from urllib.parse import quote
    url = f"{base}/admin/login/link?t={quote(link_token(email), safe='')}"
    first = (ed.get("name") or "").split(" ")[0]
    body = (emails.paragraph("The button below signs you in to the Halia content editor on this "
                             "device. It works once, for the next fifteen minutes.")
            + emails.button("Sign in", url)
            + emails.paragraph("<span style='font-size:13px;color:#8a8a8a'>Did not ask for this? "
                               "You can ignore it; nothing happens without the link.</span>"))
    html = emails.wrap("Your Halia sign-in link", body,
                       greeting=f"Hello {first}," if first else "Hello,", eyebrow="Halia")
    return notify.send_email(email, "Your Halia sign-in link", html)


def clear_session(resp) -> None:
    """Full sign-out: drop the shared session and every per-surface legacy cookie."""
    resp.delete_cookie(SESSION_COOKIE)
    for name in _LEGACY_COOKIES:
        resp.delete_cookie(name)
