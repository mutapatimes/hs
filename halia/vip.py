"""What this house actually offers, asked once and used everywhere.

Most merchants have never written a VIP policy down. They still know exactly what they would do for
a favourite client: hold something back, open early, throw in the polishing. This asks for that in
about two minutes, in plain language, with every question skippable — the goal is signal, not a
completed policy document.

The questions **branch on what they sell**, because a jeweller and a fashion house share almost no
vocabulary: one offers resizing, restringing and valuation, the other alterations, monogramming and
wardrobe consultation. Asking a jeweller about tailoring wastes the only two minutes we get.

It earns its place by constraining the AI rather than decorating it. Halia drafts replies and
suggests pieces; without this it can only write in generalities, and worse, it can offer things the
merchant does not do. A reply promising complimentary resizing to a shop that charges for it is a
promise the associate has to walk back in front of a client. So the profile is a **whitelist with
prices attached**: ``house_block`` renders it into the prompt with the instruction that nothing
outside the list may be offered, and that anything chargeable must never be described as free.

Same rule as everywhere else in the engine — the model works inside bounds the merchant set, and
never decides for them. Nothing here is ever sent to a client on its own; a person confirms
every draft.

This is merchant configuration, not customer data, so it lives in the tenant's settings blob
alongside their templates. Zero-retention is unaffected.
"""
from __future__ import annotations

from typing import Any

INDUSTRIES = [
    {"v": "fashion", "l": "Fashion & apparel"},
    {"v": "jewellery", "l": "Jewellery & watches"},
    {"v": "beauty", "l": "Beauty & fragrance"},
    {"v": "home", "l": "Home & interiors"},
    {"v": "food", "l": "Food, wine & hospitality"},
    {"v": "wellness", "l": "Health, wellness & spa"},
    {"v": "art", "l": "Art & collectables"},
    {"v": "other", "l": "Something else"},
]

# What they sell, in their own trade's words.
PRODUCTS: dict[str, list[dict]] = {
    "fashion": [{"v": "womenswear", "l": "Womenswear"}, {"v": "menswear", "l": "Menswear"},
                {"v": "shoes", "l": "Shoes"}, {"v": "bags", "l": "Bags & leather goods"},
                {"v": "accessories", "l": "Accessories"}, {"v": "outerwear", "l": "Outerwear"},
                {"v": "bridal", "l": "Bridal & occasion"}, {"v": "vintage", "l": "Vintage & archive"}],
    "jewellery": [{"v": "fine", "l": "Fine jewellery"}, {"v": "fashion_jewellery", "l": "Fashion jewellery"},
                  {"v": "bridal_rings", "l": "Engagement & bridal"}, {"v": "watches", "l": "Watches"},
                  {"v": "bespoke", "l": "Bespoke commissions"}, {"v": "estate", "l": "Antique & estate"},
                  {"v": "loose_stones", "l": "Loose stones"}],
    "beauty": [{"v": "skincare", "l": "Skincare"}, {"v": "fragrance", "l": "Fragrance"},
               {"v": "makeup", "l": "Make-up"}, {"v": "haircare", "l": "Haircare"},
               {"v": "devices", "l": "Tools & devices"}, {"v": "supplements", "l": "Supplements"}],
    "home": [{"v": "furniture", "l": "Furniture"}, {"v": "lighting", "l": "Lighting"},
             {"v": "textiles", "l": "Textiles & rugs"}, {"v": "tableware", "l": "Tableware"},
             {"v": "objects", "l": "Art & objects"}, {"v": "home_fragrance", "l": "Candles & fragrance"}],
    "food": [{"v": "wine", "l": "Wine & spirits"}, {"v": "fine_food", "l": "Fine food"},
             {"v": "hampers", "l": "Hampers & gifting"}, {"v": "venue", "l": "Restaurant or venue"}],
    "wellness": [{"v": "treatments", "l": "Treatments"}, {"v": "memberships", "l": "Memberships"},
                 {"v": "retail", "l": "Retail products"}, {"v": "retreats", "l": "Retreats"}],
    "art": [{"v": "paintings", "l": "Paintings & works on paper"}, {"v": "sculpture", "l": "Sculpture"},
            {"v": "prints", "l": "Prints & editions"}, {"v": "design", "l": "Collectable design"},
            {"v": "memorabilia", "l": "Memorabilia"}],
}

# Services offered anywhere, whatever the trade.
_COMMON_SERVICES = [
    {"v": "gift_wrap", "l": "Gift wrapping & personalisation"},
    {"v": "private_appt", "l": "Private appointments"},
    {"v": "white_glove", "l": "Delivery or white-glove service"},
    {"v": "events", "l": "Event invitations"},
    {"v": "returns", "l": "Returns handled personally"},
]

SERVICES: dict[str, list[dict]] = {
    "fashion": [{"v": "alterations", "l": "Alterations & tailoring"},
                {"v": "made_to_order", "l": "Made to order"},
                {"v": "styling", "l": "Styling or personal shopping"},
                {"v": "monogramming", "l": "Monogramming"},
                {"v": "repairs", "l": "Repairs"},
                {"v": "garment_care", "l": "Garment care & cleaning"},
                {"v": "wardrobe", "l": "Wardrobe consultation"}],
    "jewellery": [{"v": "polishing", "l": "Polishing & cleaning"},
                  {"v": "resizing", "l": "Resizing"},
                  {"v": "engraving", "l": "Engraving"},
                  {"v": "restoration", "l": "Repairs & restoration"},
                  {"v": "valuation", "l": "Valuation & certification"},
                  {"v": "commission", "l": "Bespoke commissions"},
                  {"v": "restringing", "l": "Restringing"},
                  {"v": "servicing", "l": "Watch servicing & batteries"},
                  {"v": "trade_in", "l": "Trade-in or part exchange"}],
    "beauty": [{"v": "consultation", "l": "Consultations"},
               {"v": "blending", "l": "Custom blending"},
               {"v": "refills", "l": "Refills"},
               {"v": "samples", "l": "Samples & discovery sets"},
               {"v": "treatments", "l": "Treatments & facials"},
               {"v": "masterclass", "l": "Masterclasses"}],
    "home": [{"v": "interior", "l": "Interior consultation"},
             {"v": "made_to_measure", "l": "Made to measure"},
             {"v": "installation", "l": "Delivery & installation"},
             {"v": "restoration", "l": "Restoration"},
             {"v": "samples", "l": "Fabric & finish samples"}],
    "food": [{"v": "tastings", "l": "Tastings"},
             {"v": "cellar", "l": "Cellar & storage advice"},
             {"v": "sourcing", "l": "Sourcing rare bottles or lots"},
             {"v": "private_dining", "l": "Private dining"},
             {"v": "hampers", "l": "Bespoke hampers"}],
    "wellness": [{"v": "consultation", "l": "Consultations"},
                 {"v": "programmes", "l": "Bespoke programmes"},
                 {"v": "home_visits", "l": "Home visits"},
                 {"v": "memberships", "l": "Memberships"}],
    "art": [{"v": "framing", "l": "Framing"},
            {"v": "authentication", "l": "Authentication & provenance"},
            {"v": "restoration", "l": "Restoration & conservation"},
            {"v": "installation", "l": "Delivery & installation"},
            {"v": "viewing", "l": "Private viewings"},
            {"v": "sourcing", "l": "Sourcing & commissions"}],
}

# How a service is charged for. "vip" is the whole point of the exercise: the thing they would
# waive for someone who matters, which is usually the most valuable card an associate can play.
TERMS = [
    {"v": "free", "l": "Complimentary", "hint": "for anyone"},
    {"v": "vip", "l": "Complimentary for a top client", "hint": "chargeable otherwise"},
    {"v": "paid", "l": "Chargeable", "hint": "always"},
]
_TERM_WORD = {"free": "complimentary",
              "vip": "complimentary for a top client, chargeable otherwise",
              "paid": "chargeable"}

PERKS = [
    {"v": "early_access", "l": "Early access to new arrivals"},
    {"v": "advisor", "l": "A dedicated personal advisor"},
    {"v": "after_hours", "l": "After-hours or private appointments"},
    {"v": "waitlist", "l": "Priority waitlist access"},
    {"v": "invitations", "l": "Invitations to events and launches"},
    {"v": "shipping", "l": "Expedited shipping or returns"},
    {"v": "gifting", "l": "Special-occasion gifting"},
    {"v": "hold", "l": "Holding pieces back for them"},
]

QUESTIONS: list[dict] = [
    {"key": "industry", "type": "one", "title": "What do you sell?",
     "hint": "So the rest of these questions use your language, not a generic retail script.",
     "options": INDUSTRIES},
    {"key": "products", "type": "many", "title": "Which of these do you carry?",
     "hint": "Tick anything you stock. Skip if it varies.", "by_industry": "products"},
    {"key": "services", "type": "many", "title": "What can you do for someone, beyond selling?",
     "hint": "Tick anything you offer today, however informally.", "by_industry": "services"},
    {"key": "terms", "type": "terms", "title": "Which of those are complimentary?",
     "hint": "So Halia never offers something free that you charge for, and never misses "
             "something you would happily waive."},
    {"key": "perks", "type": "many",
     "title": "If your best client walked in tomorrow, what else would you want to offer?",
     "hint": "Even if it is not written down anywhere yet. This is the one that matters most.",
     "options": PERKS, "free": "vip_offer",
     "free_label": "Anything else you would do for them, in your own words",
     "free_hint": "For example: we would open on a Sunday, or hold the whole collection back."},
    {"key": "definition", "type": "one", "title": "How do you decide who counts as a VIP?",
     "hint": "Going by feel is a real answer, and a common one.",
     "options": [{"v": "spend", "l": "By what they spend"},
                 {"v": "frequency", "l": "By how often they buy"},
                 {"v": "relationship", "l": "By relationship or referral"},
                 {"v": "feel", "l": "No formal rule yet, we go by feel"}]},
    {"key": "tone", "type": "one", "title": "How should Halia sound on your behalf?",
     # No "when should you escalate" question: Halia never sends anything, so it is always a
     # person. Asking would imply an autonomy the product does not have.
     "hint": "Every message is still yours to approve before it goes.",
     "options": [{"v": "warm", "l": "Warm and personal"},
                 {"v": "formal", "l": "Polished and formal"},
                 {"v": "playful", "l": "Playful and casual"},
                 {"v": "discreet", "l": "Discreet and exclusive"}]},
]

_BY_KEY = {q["key"]: q for q in QUESTIONS}
_FREE_KEYS = {q["free"] for q in QUESTIONS if q.get("free")}
_POOLS = {"products": PRODUCTS, "services": SERVICES}
_TONE_WORDS = {
    "warm": "warm and personal, as though you know them",
    "formal": "polished and formal",
    "playful": "light and conversational",
    "discreet": "discreet and understated, never effusive",
}


def options_for(key: str, industry: str = "") -> list[dict]:
    """The options a question offers, for this trade. Common services are appended to every
    trade's own list, so gift wrapping is offered to a jeweller and a wine merchant alike."""
    q = _BY_KEY.get(key) or {}
    if not q.get("by_industry"):
        return q.get("options") or []
    pool = _POOLS[q["by_industry"]]
    own = pool.get(industry) or []
    if q["by_industry"] == "services":
        return own + _COMMON_SERVICES
    return own


def _all_values(key: str) -> set:
    """Every value this question could legitimately hold, across all trades. Cleaning accepts any
    of them: a merchant who switches industry keeps what they already ticked, and an invented
    value is still refused."""
    q = _BY_KEY.get(key) or {}
    if not q.get("by_industry"):
        return {o["v"] for o in (q.get("options") or [])}
    vals = {o["v"] for opts in _POOLS[q["by_industry"]].values() for o in opts}
    if q["by_industry"] == "services":
        vals |= {o["v"] for o in _COMMON_SERVICES}
    return vals


def clean_profile(raw: Any) -> dict:
    """Keep only answers the questionnaire actually offers. Unknown keys and invented values are
    dropped, so a hand-posted payload cannot widen what the AI may offer or make a charged service
    look free."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for q in QUESTIONS:
        key, got = q["key"], raw.get(q["key"])
        if q["type"] == "terms":
            continue                                   # handled below, against the kept services
        allowed = _all_values(key)
        if q["type"] == "one":
            if isinstance(got, str) and got in allowed:
                out[key] = got
        else:
            picks = [v for v in (got or []) if isinstance(v, str) and v in allowed]
            if picks:
                out[key] = picks
    terms = raw.get("terms") if isinstance(raw.get("terms"), dict) else {}
    kept = {s: t for s, t in terms.items()
            if s in set(out.get("services") or []) and t in {o["v"] for o in TERMS}}
    if kept:
        out["terms"] = kept
    for key in _FREE_KEYS:
        text = str(raw.get(key) or "").strip()[:600]
        if text:
            out[key] = text
    return out


def answered(profile: Any) -> int:
    return len(clean_profile(profile))


def _label(key: str, value: str) -> str:
    for o in options_for(key) if not (_BY_KEY.get(key) or {}).get("by_industry") else []:
        if o["v"] == value:
            return o["l"]
    q = _BY_KEY.get(key) or {}
    if q.get("by_industry"):
        pool = _POOLS[q["by_industry"]]
        for opts in list(pool.values()) + ([_COMMON_SERVICES] if q["by_industry"] == "services" else []):
            for o in opts:
                if o["v"] == value:
                    return o["l"]
    for o in q.get("options") or []:
        if o["v"] == value:
            return o["l"]
    return value


def _labels(key: str, values) -> list[str]:
    if isinstance(values, str):
        values = [values]
    return [_label(key, v) for v in (values or [])]


def house_block(profile: Any) -> str:
    """The profile as a prompt fragment, or "" when nothing has been answered.

    The closing instruction is the point of the whole feature: work within what the merchant said
    they offer, on the terms they said, and invent nothing on their behalf."""
    p = clean_profile(profile)
    if not p:
        return ""
    lines = ["THIS HOUSE"]
    if p.get("industry"):
        lines.append("Trade: " + ", ".join(_labels("industry", p["industry"])))
    if p.get("products"):
        lines.append("Sells: " + ", ".join(_labels("products", p["products"])))
    if p.get("services"):
        terms = p.get("terms") or {}
        bits = []
        for v in p["services"]:
            word = _TERM_WORD.get(terms.get(v))
            bits.append(f"{_label('services', v)} ({word})" if word else _label("services", v))
        lines.append("Services they offer: " + ", ".join(bits))
    if p.get("perks"):
        lines.append("Willing to extend to a top client: " + ", ".join(_labels("perks", p["perks"])))
    if p.get("vip_offer"):
        lines.append(f'In their own words: "{p["vip_offer"]}"')
    if p.get("definition") == "feel":
        lines.append("They have no formal VIP rule and judge by feel, so treat a strong buying "
                     "history or a direct request for the owner as the tell.")
    lines.append(
        "\nOffer only what is listed above. Never describe a chargeable service as free, and where "
        "something is complimentary only for a top client, offer it as the gesture it is. If a "
        "client asks for anything not listed, say you will check rather than promising it, and "
        "never invent a service, a price or a timeframe on this merchant's behalf.")
    return "\n".join(lines)


def tone_line(profile: Any) -> str:
    """The house voice, as one instruction. Empty when they have not said."""
    tone = clean_profile(profile).get("tone")
    return f"Write {_TONE_WORDS[tone]}." if tone in _TONE_WORDS else ""
