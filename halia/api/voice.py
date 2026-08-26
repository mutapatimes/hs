"""House-voice endpoints: the instant sample, the model preview, and template rewrites.

Nothing here touches a customer. It reads the merchant's settings and templates, and returns
proposals the dashboard applies client-side (the normal Save persists them).
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, HTTPException

from halia import config, voice as V
from halia.api.shopify_auth import require_shop, shop_store

_PREVIEW_SYSTEM = (
    "You rewrite one client message for a luxury retailer in the house voice described. Keep the "
    "meaning and every {placeholder} exactly as given. Plain text only, no markdown, no emoji, "
    "no em dashes. Return only the message."
)

_REWRITE_SYSTEM = (
    "You rewrite a luxury retailer's message templates into the house voice described, in the "
    "language given. For each template keep its purpose, its name and category unchanged, and "
    "keep every {placeholder} token exactly as it appears (for example {first_name}, {sender}, "
    "{catalog_link}). Subject lines stay short. Plain text only, no markdown, no emoji, no em "
    "dashes. Never invent facts, offers, prices or dates that are not in the original."
)

_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "templates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["name", "subject", "body"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["templates"],
    "additionalProperties": False,
}


def _ai_ok(shop: str, metric: str) -> bool:
    from halia import llm
    cap = config.LLM_WEEKLY_CAP
    used = shop_store().shop_metric(shop, metric) if cap else 0
    return llm.available() and (not cap or used < cap)


def register(app) -> None:
    @app.get("/v1/voice/languages")
    def languages() -> dict:
        return {"languages": [{"code": c, "name": n} for c, n in V.LANGUAGES],
                "axes": {k: {"low": lo, "high": hi} for k, (lo, hi) in V.AXIS_LABELS.items()}}

    @app.post("/v1/voice/preview")
    def preview(shop: str = Depends(require_shop), body: Any = Body(default=None)) -> dict:
        """The sample letter in a voice. Instant by default; ``ai: true`` asks the model to
        render it (which is also how a non-English sample is produced)."""
        from halia import llm
        from halia.api import data
        from halia.api.settings import settings_for

        body = body or {}
        voice = V.clean_voice(body.get("voice"))
        s = settings_for(shop)
        sender = (s.get("sender_name") or "").strip() or "Sarah"
        sample = V.sample_message(voice, sender=sender)
        out = {"sample": sample, "voice": voice, "ai_available": llm.available()}
        if body.get("ai") and _ai_ok(shop, "voice_preview_ai"):
            text = llm.complete(_PREVIEW_SYSTEM,
                                V.voice_brief(voice) + "\n\nMessage to rewrite:\n" + sample,
                                max_tokens=500)
            if text:
                out["ai"] = text.strip()
                data.record_activity(shop, "voice_preview_ai")
        return out

    @app.post("/v1/voice/rewrite")
    def rewrite(shop: str = Depends(require_shop), body: Any = Body(default=None)) -> dict:
        """Rewrite the merchant's client templates into a voice and language. Returns proposals;
        the dashboard applies them into the editor and the ordinary Save persists them."""
        from halia import llm
        from halia.api import data
        from halia.api.settings import settings_for

        body = body or {}
        voice = V.clean_voice(body.get("voice"))
        if not _ai_ok(shop, "voice_rewrite_ai"):
            raise HTTPException(409, "AI rewriting is off for this store right now.")
        templates = body.get("templates")
        if not isinstance(templates, list) or not templates:
            templates = settings_for(shop).get("email_templates") or []
        templates = [t for t in templates if isinstance(t, dict) and t.get("body")][:40]
        if not templates:
            raise HTTPException(422, "There are no templates to rewrite.")

        listing = "\n\n".join(
            f"[{i+1}] name: {t.get('name','')}\nsubject: {t.get('subject','')}\nbody:\n{t.get('body','')}"
            for i, t in enumerate(templates))
        got = llm.structured(_REWRITE_SYSTEM,
                             V.voice_brief(voice) + f"\n\nRewrite these {len(templates)} templates, "
                             "returning them in the same order with the same names:\n\n" + listing,
                             _REWRITE_SCHEMA, max_tokens=4000)
        if not got or not got.get("templates"):
            raise HTTPException(502, "The rewrite did not come back cleanly. Try again.")
        data.record_activity(shop, "voice_rewrite_ai")

        # Merge by position (names are asked to stay put; fall back to name match).
        by_name = {str(t.get("name", "")).strip().lower(): t for t in got["templates"]}
        out = []
        for i, orig in enumerate(templates):
            new = got["templates"][i] if i < len(got["templates"]) else \
                by_name.get(str(orig.get("name", "")).strip().lower())
            merged = dict(orig)
            if new:
                merged["subject"] = str(new.get("subject") or orig.get("subject") or "")[:200]
                merged["body"] = str(new.get("body") or orig.get("body") or "")[:4000]
            out.append(merged)
        return {"templates": out, "voice": voice, "count": len(out)}
