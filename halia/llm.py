"""A tiny, dependency-free client for one Claude call: the engine behind the extension's message
drafter ("Draft with Halia").

We send the client's live standing (the same warm book the dashboard scores from) and the visible
thread the associate is already looking at, and get back one suggested reply. Zero-retention holds:
the context is used in-flight and nothing about the customer is stored. When no key is configured,
or a call fails for any reason, ``complete`` returns ``None`` so the caller falls back to a
template, which is why the feature always works without AI.

The Anthropic Messages API is a single HTTPS POST, so we use the ``httpx`` already in the stack
rather than adding an SDK.
"""
from __future__ import annotations

from typing import Optional

import httpx

from halia import config

_API = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"


def available() -> bool:
    """Whether AI drafting is configured. False -> callers fall back to templates."""
    return bool(config.LLM_API_KEY)


def complete(system: str, user: str, *, model: Optional[str] = None,
             max_tokens: int = 600, timeout: float = 15.0) -> Optional[str]:
    """One Claude message. Returns the reply text, or ``None`` on any failure (missing key,
    network error, non-200, empty body) so the caller can fall back. Never raises."""
    key = config.LLM_API_KEY
    if not key:
        return None
    body = {
        "model": model or config.LLM_MODEL,
        "max_tokens": max(64, int(max_tokens)),
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        res = httpx.post(_API, json=body, timeout=timeout, headers={
            "x-api-key": key,
            "anthropic-version": _VERSION,
            "content-type": "application/json",
        })
    except Exception:  # noqa: BLE001 — a drafting hiccup must never break the request
        return None
    if res.status_code != 200:
        return None
    try:
        parts = res.json().get("content") or []
    except Exception:  # noqa: BLE001 — malformed body -> fall back
        return None
    text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
    return text or None
