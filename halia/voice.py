"""The house voice: four sliders and a language, applied to everything Halia writes.

A merchant sets how their house sounds once, with sliders (formal, exclusive, attentive,
polished) and a language. The profile shapes AI drafting and template rewrites, and renders an
instant sample so the sliders feel alive without a model call. All settings-level; nothing
about any customer is involved.
"""
from __future__ import annotations

from typing import Any

AXES = ("formality", "exclusivity", "attentiveness", "polish")

# Left/right poles, in the merchant's language, not ours.
AXIS_LABELS = {
    "formality":     ("Relaxed", "Formal"),
    "exclusivity":   ("Open to all", "Exclusive"),
    "attentiveness": ("Light touch", "Attentive"),
    "polish":        ("Casual", "Suited and booted"),
}

LANGUAGES = [
    ("en", "English"), ("fr", "French"), ("it", "Italian"), ("de", "German"),
    ("es", "Spanish"), ("pt", "Portuguese"), ("nl", "Dutch"), ("ar", "Arabic"),
    ("ja", "Japanese"), ("zh", "Chinese"), ("ko", "Korean"), ("ru", "Russian"),
]
_LANG = dict(LANGUAGES)

DEFAULT_VOICE = {"formality": 70, "exclusivity": 60, "attentiveness": 65, "polish": 70,
                 "language": "en"}


def clean_voice(raw: Any) -> dict:
    """A voice profile with every axis clamped to 0-100 and a known language."""
    d = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for axis in AXES:
        try:
            v = int(float(d.get(axis, DEFAULT_VOICE[axis])))
        except (TypeError, ValueError):
            v = DEFAULT_VOICE[axis]
        out[axis] = max(0, min(100, v))
    lang = str(d.get("language") or "en").strip().lower()[:5]
    out["language"] = lang if lang in _LANG else "en"
    return out


def language_name(code: str) -> str:
    return _LANG.get(code, "English")


def _band(v: int) -> str:
    return "low" if v < 34 else ("high" if v > 66 else "mid")


def voice_brief(voice: Any) -> str:
    """The profile as one instruction block for a model. Concrete, so the output actually moves
    when a slider moves."""
    v = clean_voice(voice)
    parts = []
    parts.append({
        "low": "Register: relaxed and conversational, first names, contractions welcome.",
        "mid": "Register: warm but composed; polite without being stiff.",
        "high": "Register: formal; full sentences, no contractions, courteous distance.",
    }[_band(v["formality"])])
    parts.append({
        "low": "Access: welcoming and open; everyone is invited, nothing is gated.",
        "mid": "Access: quietly selective; mention private previews or appointments where natural.",
        "high": "Access: discreetly exclusive; speak of private views, first refusal, and pieces set "
                "aside, as a house that chooses its clients.",
    }[_band(v["exclusivity"])])
    parts.append({
        "low": "Service: light touch; make the offer once and leave the door open.",
        "mid": "Service: attentive; anticipate one need and offer to handle it.",
        "high": "Service: butler-like; anticipate needs, take care of every detail, and make clear "
                "nothing is any trouble.",
    }[_band(v["attentiveness"])])
    parts.append({
        "low": "Polish: casual and human; short lines, plain words.",
        "mid": "Polish: well-turned; crisp sentences, a little grace in the phrasing.",
        "high": "Polish: suited and booted; immaculate phrasing, classic courtesies, nothing loose.",
    }[_band(v["polish"])])
    parts.append(f"Language: write in {language_name(v['language'])}.")
    return "House voice.\n" + "\n".join(parts)


# ── the instant sample ───────────────────────────────────────────────────────

_GREETING = {
    "low":  "Hi {first_name},",
    "mid":  "Dear {first_name},",
    "high": "Dear {first_name},",
}
_OPENER = {  # attentiveness
    "low":  "Just a quick note to say the new season has arrived, and I thought of you.",
    "mid":  "The new season has arrived and a few pieces made me think of you straight away.",
    "high": "The new season has arrived, and I have already set aside the pieces I believe you "
            "will want to see first, in your size.",
}
_OFFER = {  # exclusivity
    "low":  "Come by whenever you like; we would love to show you around.",
    "mid":  "If you would like a private look before the collection goes on the floor, I would "
            "be glad to arrange it.",
    "high": "I am holding a private view for a handful of clients before anything reaches the "
            "floor. Your place is kept, should you wish to take it.",
}
_CLOSE = {  # polish
    "low":  "Let me know what works!",
    "mid":  "Do let me know what suits, and I will take care of the rest.",
    "high": "It would be my pleasure to arrange everything to your convenience.",
}
_SIGN = {  # formality
    "low":  "Best,\n{sender}",
    "mid":  "Warm regards,\n{sender}",
    "high": "With kind regards,\n{sender}",
}


def sample_message(voice: Any, first_name: str = "Charlotte", sender: str = "Sarah") -> str:
    """A deterministic sample in the voice: the sliders move, the letter changes, instantly.
    Rendered in English; other languages are shown through the model preview."""
    v = clean_voice(voice)
    f, e, a, p = (_band(v[k]) for k in AXES)
    body = "\n\n".join([
        _GREETING[f].format(first_name=first_name),
        _OPENER[a],
        _OFFER[e],
        _CLOSE[p],
        _SIGN[f].format(sender=sender),
    ])
    if f == "low":
        body = body.replace("I am ", "I'm ").replace("I would ", "I'd ").replace("you will ", "you'll ")
    return body
