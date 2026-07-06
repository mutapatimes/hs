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


def _sign(exp: int) -> str:
    return hmac.new(_secret(), f"staff|{exp}".encode(), hashlib.sha256).hexdigest()


def make_session(ttl: int = _TTL) -> str:
    exp = int(time.time()) + ttl
    return f"{exp}|{_sign(exp)}"


def session_ok(request: Request) -> bool:
    """True if the request carries a valid, unexpired shared staff session."""
    raw = request.cookies.get(SESSION_COOKIE) or ""
    try:
        exp_s, sig = raw.split("|", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    return exp >= int(time.time()) and hmac.compare_digest(sig, _sign(exp))


def _secure() -> bool:
    return (config.HALIA_APP_URL or "").startswith("https")


def set_session(resp, ttl: int = _TTL) -> None:
    """Attach the shared session cookie to a response (called on any surface's sign-in)."""
    resp.set_cookie(SESSION_COOKIE, make_session(ttl), httponly=True, secure=_secure(),
                    samesite="lax", max_age=ttl)


def clear_session(resp) -> None:
    """Full sign-out: drop the shared session and every per-surface legacy cookie."""
    resp.delete_cookie(SESSION_COOKIE)
    for name in _LEGACY_COOKIES:
        resp.delete_cookie(name)
