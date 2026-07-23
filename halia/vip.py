"""What this house actually offers, asked once and used everywhere.

Most merchants have never written a VIP policy down. They still know exactly what they would do for
a favourite client: hold something back, open early, throw in the alterations. This asks for that in
about two minutes, in plain language, with every question skippable — the goal is signal, not a
completed policy document.

It earns its place by constraining the AI rather than decorating it. Halia drafts replies and
suggests next moves; without this it can only write in generalities, and worse, it can offer things
the merchant does not do. A reply promising complimentary alterations to a shop that does not alter
is a promise the associate has to walk back in front of a client.

So the profile is a **whitelist**: ``house_block`` renders it into the prompt with the instruction
that nothing outside the list may be offered. Same rule as everywhere else in the engine — the model
proposes within bounds the merchant set, and never decides for them. Nothing here is ever sent to a
client on its own; every draft is still confirmed by a person.

This is merchant configuration, not customer data, so it is stored in the tenant's settings blob
alongside their templates. Zero-retention is unaffected.
"""
from __future__ import annotations

from typing import Any

# The questionnaire, defined once and served to the UI so the wording, the options and the values
# can never drift apart. Every step is skippable; order is the order it is asked in.
QUESTIONS: list[dict] = [
    {
        "key": "industry", "type": "one", "title": "What do you sell?",
        "hint": "So suggestions use your language, not a generic retail script.",
        "options": [
            {"v": "fashion", "l": "Fashion & apparel"},
            {"v": "beauty", "l": "Beauty & grooming"},
            {"v": "jewellery", "l": "Jewellery & watches"},
            {"v": "home", "l": "Home & interiors"},
            {"v": "food", "l": "Food, wine & hospitality"},
            {"v": "wellness", "l": "Health, wellness & spa"},
            {"v": "other", "l": "Something else"},
        ],
    },
    {
        "key": "services", "type": "many", "title": "What can you already do for someone?",
        "hint": "Tick anything you offer today, however informally.",
        "options": [
            {"v": "styling", "l": "Styling or personal shopping"},
            {"v": "alterations", "l": "Alterations & tailoring"},
            {"v": "made_to_order", "l": "Made to order or customisation"},
            {"v": "gift_wrap", "l": "Gift wrapping & personalisation"},
            {"v": "engraving", "l": "Engraving"},
            {"v": "repairs", "l": "Repairs & restoration"},
            {"v": "white_glove", "l": "Delivery or white-glove service"},
            {"v": "events", "l": "Event invitations"},
        ],
    },
    {
        "key": "appointments", "type": "one", "title": "Do you take appointments?",
        "hint": "Video, in person, or not yet.",
        "options": [
            {"v": "video", "l": "Yes, including video"},
            {"v": "in_person", "l": "Yes, in person"},
            {"v": "no", "l": "Not at the moment"},
            {"v": "open", "l": "Not yet, but we would"},
        ],
    },
    {
        "key": "perks", "type": "many",
        "title": "If your best client walked in tomorrow, what would you want to offer them?",
        "hint": "Even if it is not written down anywhere yet. This is the one that matters most.",
        "free": "vip_offer",
        "free_label": "Anything else you would do for them, in your own words",
        "free_hint": "For example: we would open on a Sunday, or hold the whole collection back.",
        "options": [
            {"v": "early_access", "l": "Early access to new arrivals"},
            {"v": "advisor", "l": "A dedicated personal advisor"},
            {"v": "after_hours", "l": "After-hours or private appointments"},
            {"v": "free_alterations", "l": "Complimentary alterations or personalisation"},
            {"v": "waitlist", "l": "Priority waitlist access"},
            {"v": "invitations", "l": "Invitations to events and launches"},
            {"v": "shipping", "l": "Expedited shipping or returns"},
            {"v": "gifting", "l": "Special-occasion gifting"},
        ],
    },
    {
        "key": "definition", "type": "one", "title": "How do you decide who counts as a VIP?",
        "hint": "Going by feel is a real answer, and a common one.",
        "options": [
            {"v": "spend", "l": "By what they spend"},
            {"v": "frequency", "l": "By how often they buy"},
            {"v": "relationship", "l": "By relationship or referral"},
            {"v": "feel", "l": "No formal rule yet, we go by feel"},
        ],
    },
    {
        "key": "tone", "type": "one", "title": "How should Halia sound on your behalf?",
        "hint": "Every message is still yours to approve before it goes.",
        "free": "escalate",
        "free_label": "When should Halia hand a conversation to a person?",
        "free_hint": "For example: anything over £2,000, or any complaint.",
        "options": [
            {"v": "warm", "l": "Warm and personal"},
            {"v": "formal", "l": "Polished and formal"},
            {"v": "playful", "l": "Playful and casual"},
            {"v": "discreet", "l": "Discreet and exclusive"},
        ],
    },
]

_BY_KEY = {q["key"]: q for q in QUESTIONS}
_FREE_KEYS = {q["free"] for q in QUESTIONS if q.get("free")}
_TONE_WORDS = {
    "warm": "warm and personal, as though you know them",
    "formal": "polished and formal",
    "playful": "light and conversational",
    "discreet": "discreet and understated, never effusive",
}


def clean_profile(raw: Any) -> dict:
    """Keep only answers the questionnaire actually offers. Unknown keys and invented option
    values are dropped, so a hand-posted payload cannot widen what the AI may offer."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for q in QUESTIONS:
        allowed = {o["v"] for o in q["options"]}
        got = raw.get(q["key"])
        if q["type"] == "one":
            if isinstance(got, str) and got in allowed:
                out[q["key"]] = got
        else:
            picks = [v for v in (got or []) if isinstance(v, str) and v in allowed]
            if picks:
                out[q["key"]] = picks
    for key in _FREE_KEYS:
        text = str(raw.get(key) or "").strip()[:600]
        if text:
            out[key] = text
    return out


def answered(profile: Any) -> int:
    """How many questions have an answer. Used to decide whether to ask again later."""
    return len(clean_profile(profile))


def _labels(key: str, values) -> list[str]:
    opts = {o["v"]: o["l"] for o in _BY_KEY[key]["options"]}
    if isinstance(values, str):
        values = [values]
    return [opts[v] for v in (values or []) if v in opts]


def house_block(profile: Any) -> str:
    """The profile as a prompt fragment, or "" when nothing has been answered.

    The closing instruction is the point of the whole feature: the model may work within what the
    merchant said they offer, and must not invent a service on their behalf."""
    p = clean_profile(profile)
    if not p:
        return ""
    lines = ["THIS HOUSE"]
    if p.get("industry"):
        lines.append("Trade: " + ", ".join(_labels("industry", p["industry"])))
    services = _labels("services", p.get("services"))
    if services:
        lines.append("Services they offer: " + ", ".join(services))
    perks = _labels("perks", p.get("perks"))
    if perks:
        lines.append("Willing to extend to a top client: " + ", ".join(perks))
    if p.get("vip_offer"):
        lines.append(f'In their own words: "{p["vip_offer"]}"')
    appt = _labels("appointments", p.get("appointments"))
    if appt:
        lines.append("Appointments: " + ", ".join(appt))
    if p.get("definition") == "feel":
        lines.append("They have no formal VIP rule and judge by feel, so treat a strong buying "
                     "history or a direct request for the owner as the tell.")
    if p.get("escalate"):
        lines.append(f'Hand to a person when: {p["escalate"]}')
    lines.append(
        "\nOffer only what is listed above. If a client asks for something that is not, say you "
        "will check rather than promising it, and never invent a service, a discount or a "
        "timeframe on this merchant's behalf.")
    return "\n".join(lines)


def tone_line(profile: Any) -> str:
    """The house voice, as one instruction. Empty when they have not said."""
    tone = clean_profile(profile).get("tone")
    return f"Write {_TONE_WORDS[tone]}." if tone in _TONE_WORDS else ""
