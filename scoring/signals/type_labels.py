"""Human labels for internal signal TYPE codes.

Signals tag matches with terse snake_case type codes (``luxury_hotel``,
``private_jet_fbo``, ``wealth_management``…) used for weighting. Those codes must
never reach a client-facing reason string. ``humanize_type`` turns them into plain
English: a bare ``_`` -> space covers most, and the map below handles jargon and
nicer phrasing. Kept dependency-free so any signal module can import it.
"""
from __future__ import annotations

# Only codes whose plain underscore->space rendering reads badly (jargon) or that
# deserve a nicer phrase. Everything else falls through to code.replace("_", " ").
_SPECIAL = {
    "private_jet_fbo": "private jet terminal",
    "sovereign_wealth": "sovereign wealth fund",
    "ivy_alumni": "Ivy League",
    "elite_alumni": "elite university",
    "members_club": "members' club",
    "royal_household": "royal household",
    "ai_lab": "AI lab",
    "quant_trading": "quant trading firm",
    "commodities_trading": "commodities trader",
}


def humanize_type(code: object) -> str:
    """'luxury_hotel' -> 'luxury hotel'; 'private_jet_fbo' -> 'private jet terminal'."""
    c = str(code or "").strip()
    if not c:
        return ""
    return _SPECIAL.get(c, c.replace("_", " "))
