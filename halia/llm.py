"""The Claude calls behind the extension's clienteling copilot.

Two shapes, both used by `halia/api/extension.py`:

    complete(system, user)               -> plain text (a drafted message)
    structured(system, user, schema)     -> a dict matching `schema` (the conversation brief)

`structured` uses the Messages API's structured outputs (`output_config.format`), so the brief
comes back as valid JSON against our schema rather than prose we have to parse.

Both return ``None`` on any failure (no key configured, network, refusal, malformed body) so every
caller falls back to the merchant's own templates and heuristics. That is why the feature works
with no AI key at all.

Zero-retention holds: the client's standing and the visible conversation are sent, used to compose
the answer, and discarded. Nothing about the customer is stored here or by the API call.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import anthropic

from halia import config

_cached: Optional[tuple] = None


def available() -> bool:
    """Whether AI is configured. False -> callers fall back to templates and heuristics."""
    return bool(config.LLM_API_KEY)


def model_for(tier: Any = None) -> str:
    """The model to use. Top-grade clients optionally get the premium model, where the extra
    prose quality earns its keep; everyone else runs on the cheap everyday model."""
    if config.LLM_MODEL_PREMIUM and str(tier or "").startswith("A"):
        return config.LLM_MODEL_PREMIUM
    return config.LLM_MODEL


def _client():
    """A cached SDK client, rebuilt if the key changes. None when no key is configured."""
    global _cached
    key = config.LLM_API_KEY
    if not key:
        return None
    if _cached is None or _cached[0] != key:
        _cached = (key, anthropic.Anthropic(api_key=key, timeout=25.0, max_retries=2))
    return _cached[1]


def _text(msg) -> Optional[str]:
    """The text of a response, or None if the model refused or returned nothing usable."""
    if getattr(msg, "stop_reason", None) == "refusal":
        return None
    out = "".join(b.text for b in msg.content if b.type == "text").strip()
    return out or None


def complete(system: str, user: str, *, model: Optional[str] = None,
             max_tokens: int = 600) -> Optional[str]:
    """One Claude message, returned as text. None on any failure, so the caller falls back."""
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(
            model=model or config.LLM_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception:  # noqa: BLE001 — a drafting hiccup must never break the request
        return None
    return _text(msg)


def structured(system: str, user: str, schema: dict, *, model: Optional[str] = None,
               max_tokens: int = 1200) -> Optional[dict]:
    """One Claude message constrained to ``schema``, returned as a dict. None on any failure.

    Structured outputs guarantee the response is valid JSON matching the schema, so there is no
    prose-parsing step and no half-formed brief to defend against downstream."""
    client = _client()
    if client is None:
        return None
    try:
        msg = client.messages.create(
            model=model or config.LLM_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except Exception:  # noqa: BLE001
        return None
    text = _text(msg)
    if not text:
        return None
    try:
        out = json.loads(text)
    except (TypeError, ValueError):
        return None
    return out if isinstance(out, dict) else None
