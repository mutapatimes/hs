"""Shared grading: raw signal score -> 0-100, tier, and the POS gesture prompt.

Single source of truth so the batch dashboard (`build_mvp`) and the real-time
single-client lookup (`scoring.realtime`) grade a client identically.

The 0-100 mapping and tier cuts are PROVISIONAL (not a calibrated model) — they
turn the raw weighted signal score (~0-8) into a friendly grade for display and
for the point-of-sale flag.
"""
from __future__ import annotations


def to_score100(raw: float) -> int:
    """Provisional 0-100 mapping of the raw weighted signal score (~0-8 range)."""
    return int(min(99, round(50 + raw * 8)))


def tier_for(s100: int) -> str:
    """Score band -> tier CODE. Display labels (GRADE_LABEL): A1='A*', A, B, C."""
    if s100 >= 90:
        return "A1"
    if s100 >= 78:
        return "A"
    if s100 >= 64:
        return "B"
    return "C"


GRADE_LABEL = {"A1": "A*", "A": "A", "B": "B", "C": "C"}

# Discreet, ACTIONABLE associate prompts for the shop floor — shown only on the
# associate's screen, NEVER to the client. The point is a specific, graceful
# gesture, not "VIP!": recognition, not surveillance. Keep it warm and low-key.
GESTURE = {
    "A1": "High-potential client — offer a coffee in the cafe and mention the private "
          "preview. Warm and low-key, no fuss.",
    "A": "Promising client — offer a coffee on us and note their interest for a "
         "personal follow-up.",
    "B": "Give a genuine warm welcome; capture an email for follow-up if they're not "
         "already on file.",
    "C": "A single soft tell — keep on the radar; no action needed yet, re-score if "
         "more signals appear.",
}


def gesture_for(tier: str | None) -> str:
    """The discreet associate prompt for a tier (empty for no/None tier)."""
    return GESTURE.get(tier or "", "")
