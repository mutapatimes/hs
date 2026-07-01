"""Shared grading: raw signal score -> 0-100, tier, and the POS gesture prompt.

Single source of truth so the batch dashboard (`build_mvp`) and the real-time
single-client lookup (`scoring.realtime`) grade a client identically.

The 0-100 mapping and tier cuts are PROVISIONAL (not a calibrated model) — they
turn the raw weighted signal score (~0-8) into a friendly grade for display and
for the point-of-sale flag.
"""
from __future__ import annotations

import math

# Logistic mapping of the raw weighted signal score (~0-8) to 0-100. Evidence is NOT linear:
# the gap between one weak tell (raw 1) and real convergent evidence (raw 3) is huge, while the
# gap between raw 6 and raw 8 is marginal. A logistic compresses the top (so a genuine 90+ is
# earned, not routine, and 99 is rare), spreads the middle where discrimination matters, and
# makes score100 behave like a CONFIDENCE — which is what latent value implicitly treats it as.
# Tuned (centre 3.5, slope 0.8) so the tier boundaries land at the SAME raw scores as before
# (A* raw>=5.0, A raw>=3.5, B raw>=1.75) — grades don't shift, only the number is honest.
_LOGIT_CENTRE = 3.5
_LOGIT_SLOPE = 0.8


def to_score100(raw: float) -> int:
    """Logistic 0-100 mapping of the raw weighted signal score. 0 signals -> ~6, not 50."""
    s = 100.0 / (1.0 + math.exp(-_LOGIT_SLOPE * (raw - _LOGIT_CENTRE)))
    return int(min(99, round(s)))


def tier_for(s100: int) -> str:
    """Score band -> tier CODE. Display labels (GRADE_LABEL): A1='A*', A, B, C.

    Cuts correspond to the historical raw boundaries under the logistic mapping:
    77≈raw5.0 (A*), 50=raw3.5 (A), 20≈raw1.75 (B) — so tiers are unchanged by the reshape.
    """
    if s100 >= 77:
        return "A1"
    if s100 >= 50:
        return "A"
    if s100 >= 20:
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
