"""Clean capture: email and postcode hygiene at the point of entry.

Bad contact details rot a client book from day one: a mistyped gmail domain is an
undeliverable client forever, and a mangled postcode starves the geography signals. These
helpers correct what can be corrected while the client is still present, and normalise what
lands either way. Everything is local: syntax, a curated typo map, a cached DNS resolve.
Client data is sent to no third party.
"""
from __future__ import annotations

import re
import socket
from functools import lru_cache

# ── email ────────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]{2,})$")

# The domains people actually mistype at a till, mapped to what they meant. Curated and
# deliberately small: a wrong "correction" is worse than none.
_DOMAIN_FIXES = {
    "gamil.com": "gmail.com", "gmial.com": "gmail.com", "gmali.com": "gmail.com",
    "gnail.com": "gmail.com", "gmaill.com": "gmail.com", "gmail.co": "gmail.com",
    "gmail.con": "gmail.com", "gmail.cm": "gmail.com", "googlemail.co": "googlemail.com",
    "hotmial.com": "hotmail.com", "hotmal.com": "hotmail.com", "hotmail.co": "hotmail.com",
    "hotmail.con": "hotmail.com", "hotmai.com": "hotmail.com",
    "outlok.com": "outlook.com", "outloo.com": "outlook.com", "outlook.co": "outlook.com",
    "outlook.con": "outlook.com",
    "yaho.com": "yahoo.com", "yahooo.com": "yahoo.com", "yahoo.con": "yahoo.com",
    "yahoo.co": "yahoo.com",
    "icloud.co": "icloud.com", "icoud.com": "icloud.com", "iclod.com": "icloud.com",
    "icloud.con": "icloud.com",
    "aol.con": "aol.com", "live.con": "live.com", "me.con": "me.com",
}

# Trailing-TLD slips that apply to any domain.
_TLD_FIXES = (
    (".con", ".com"), (".cmo", ".com"), (".ocm", ".com"), (".vom", ".com"),
    (".co,uk", ".co.uk"), (".couk", ".co.uk"),
)


@lru_cache(maxsize=4096)
def _domain_resolves(domain: str) -> bool:
    """Whether the domain exists in DNS. Cached, short-fused, and forgiving: any doubt
    (timeout, resolver hiccup) counts as fine — this check may only ever catch garbage,
    never block a real address. getaddrinfo has no timeout of its own, so it runs in a
    bounded worker; a slow resolver simply passes."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout

    def _lookup() -> bool:
        try:
            socket.getaddrinfo(domain, None)
            return True
        except socket.gaierror:
            return False
        except Exception:  # noqa: BLE001 — resolver trouble is not the client's problem
            return True

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_lookup).result(timeout=1.5)
    except _Timeout:
        return True
    except Exception:  # noqa: BLE001
        return True


def clean_email(raw: object, *, check_dns: bool = True) -> tuple[str, str | None, bool]:
    """(normalised email, suggested correction or None, looks deliverable).

    The suggestion is offered, never silently applied: the client (or associate) confirms it.
    """
    email = str(raw or "").strip().lower().rstrip(".")
    if not email:
        return "", None, False
    m = _EMAIL_RE.match(email)
    if not m:
        return email, None, False
    local, domain = email.rsplit("@", 1)

    suggestion = None
    fixed = _DOMAIN_FIXES.get(domain)
    if fixed is None:
        for bad, good in _TLD_FIXES:
            if domain.endswith(bad):
                candidate = domain[: -len(bad)] + good
                # Only suggest a TLD fix when it lands on a domain that resolves (or when
                # DNS checking is off): ".con" on a made-up domain proves nothing.
                if not check_dns or _domain_resolves(candidate):
                    fixed = candidate
                break
    if fixed and fixed != domain:
        suggestion = f"{local}@{fixed}"

    ok = True
    if check_dns and suggestion is None:
        ok = _domain_resolves(domain)
    return email, suggestion, ok


# ── postcode ─────────────────────────────────────────────────────────────────

# The official UK postcode shape: outward (area letters + district) + inward (digit + 2 letters).
_UK_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}[0-9][0-9A-Z]?[0-9][A-Z]{2}$")
_UK_OUTCODE_RE = re.compile(r"^[A-Z]{1,2}[0-9][0-9A-Z]?$")

_UK_COUNTRIES = {"", "uk", "gb", "united kingdom", "great britain", "england", "scotland",
                 "wales", "northern ireland"}


def clean_postcode(raw: object, country: object = "") -> tuple[str, bool]:
    """(normalised postcode, looks valid).

    UK postcodes are re-spaced and shape-checked ("sw1a1aa" -> "SW1A 1AA"); a bare outward
    code passes ("SW10"). Other countries pass through trimmed and upper-cased, unjudged —
    a wrong "invalid" would block a real address.
    """
    text = re.sub(r"\s+", "", str(raw or "").strip().upper())
    if not text:
        return "", True
    if str(country or "").strip().lower() not in _UK_COUNTRIES:
        return re.sub(r"\s+", " ", str(raw or "").strip().upper()), True
    if _UK_POSTCODE_RE.match(text):
        return f"{text[:-3]} {text[-3:]}", True
    if _UK_OUTCODE_RE.match(text):
        return text, True
    return re.sub(r"\s+", " ", str(raw or "").strip().upper()), False
