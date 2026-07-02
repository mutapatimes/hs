"""Conversion-feedback calibration.

The signal weights in ``scoring.combine.SIGNAL_WEIGHTS`` are sensible constants, but the
signals that actually predict *spend* differ from merchant to merchant: for one house a
prime postcode is decisive, for another it's a work email. This module learns that from a
merchant's own scored data and re-tunes the weights accordingly — the loop the FAQ promises.

How it works (and its honest limits)
-------------------------------------
Given a scored frame (signal flag columns + a ``Spent`` column), for each signal we measure
its **spend lift**: the mean spend of customers for whom the signal fired, divided by the
mean spend across all customers. Lift > 1 means "when this signal fires, this merchant's
customers spend more than average" → the signal earns a higher weight; lift < 1 → lower.

**DIRECTIONAL-BIAS WARNING (read before trusting these numbers).** This calibrates on a
*snapshot* of realised spend, not on a longitudinal "did this flagged hidden-VIC later convert"
label. That is not merely a data limitation — it is a bias *against Halia's own thesis*. The
product exists to find people whose wealth signals fire *despite* low current spend; a signal
that is brilliant at that (e.g. `wealth_structure`) will show WEAK spend lift precisely because
its best catches haven't converted yet, and naive calibration would down-weight it toward the
signals that merely track existing spend — i.e. RFM through the back door, erasing the
differentiator. So v1 is deliberately **timid**: adjustments are tightly bounded (a weight can
move at most ~±25%) and gated on a minimum sample, and this is offered preview-first, not
auto-applied. The real fix is to calibrate on **conversion outcomes** (did surfaced VICs become
top clients) once that longitudinal / associate-feedback data exists; until then, prefer small
nudges over big swings, and never let it zero the hidden-wealth signals.

Everything here is pure and offline: it reads a frame, returns numbers / a new weights dict.
Nothing is persisted; the caller decides whether to adopt the suggested weights.

**Outcome-based calibration (the real fix).** The functions at the bottom
(`calibrate_from_feedback`) re-weight on associate FEEDBACK precision — did surfaced clients turn
out to be a "good call"? — instead of on spend. That removes the directional bias entirely (it
rewards signals whose catches the merchant confirmed, even if they haven't spent yet), so its
bounds are looser than the timid spend-based ones. It consumes the aggregate feedback tally from
`store.feedback_stats` (populated by /v1/feedback). Prefer it over spend calibration once a
merchant has given enough verdicts.
"""
from __future__ import annotations

import pandas as pd

from scoring.combine import SIGNAL_WEIGHTS, active_signals

SPEND_COL = "Spent"
# Don't move a weight unless at least this many customers fired the signal — protects
# against a couple of big spenders swinging a rarely-fired signal.
MIN_FIRED = 25
# Bound how far one calibration pass can move a weight (multiplier on the base weight). Kept
# TIGHT on purpose (see the directional-bias warning above): snapshot spend lift is biased
# against hidden-wealth signals, so v1 nudges (±25%), it does not swing (±100%).
LO, HI = 0.8, 1.25


def _spend(df: pd.DataFrame, spend_col: str) -> pd.Series:
    if spend_col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[spend_col], errors="coerce").fillna(0.0)


def signal_lift(
    scored: pd.DataFrame,
    spend_col: str = SPEND_COL,
    include_origin: bool = False,
) -> list[dict]:
    """Per-signal spend lift over the whole base, richest first.

    Returns one dict per in-scope signal that has a flag column present:
    ``{key, label, n_fired, mean_spend_fired, mean_spend_overall, lift}``.
    ``lift`` is None when it can't be computed (no firers, or zero overall spend).
    """
    spent = _spend(scored, spend_col)
    overall = float(spent.mean()) if len(spent) else 0.0
    rows: list[dict] = []
    for key, label, _apply, flag_col, _reason in active_signals(include_origin):
        if flag_col not in scored.columns:
            continue
        fired = scored[flag_col].fillna(False).astype(bool)
        n = int(fired.sum())
        mean_fired = float(spent[fired].mean()) if n else 0.0
        lift = (mean_fired / overall) if (n and overall > 0) else None
        rows.append({
            "key": key,
            "label": label,
            "n_fired": n,
            "mean_spend_fired": round(mean_fired, 2),
            "mean_spend_overall": round(overall, 2),
            "lift": round(lift, 3) if lift is not None else None,
        })
    rows.sort(key=lambda r: (r["lift"] is not None, r["lift"] or 0), reverse=True)
    return rows


def calibrate_weights(
    scored: pd.DataFrame,
    base_weights: dict[str, int] | None = None,
    spend_col: str = SPEND_COL,
    min_fired: int = MIN_FIRED,
    lo: float = LO,
    hi: float = HI,
    include_origin: bool = False,
) -> dict[str, int]:
    """Return a new weights dict, base weights re-scaled by each signal's measured lift.

    A signal is only adjusted when at least ``min_fired`` customers fired it and its lift is
    computable; otherwise it keeps its base weight. The multiplier (bounded to [lo, hi]) is
    the lift itself. Weights stay >= 1 for any signal that had a base weight (calibration
    down-weights, it never switches a signal off — that's a deliberate product decision).
    """
    base = dict(base_weights or SIGNAL_WEIGHTS)
    lifts = {r["key"]: r for r in signal_lift(scored, spend_col, include_origin)}
    out = dict(base)
    for key, b in base.items():
        info = lifts.get(key)
        if not info or info["lift"] is None or info["n_fired"] < min_fired:
            continue
        mult = max(lo, min(hi, info["lift"]))
        new = round(b * mult)
        out[key] = max(1, int(new)) if b >= 1 else int(new)
    return out


def calibration_report(
    scored: pd.DataFrame,
    base_weights: dict[str, int] | None = None,
    spend_col: str = SPEND_COL,
    min_fired: int = MIN_FIRED,
    include_origin: bool = False,
) -> list[dict]:
    """Rows for display: lift + base vs suggested weight + a plain-English note."""
    base = dict(base_weights or SIGNAL_WEIGHTS)
    suggested = calibrate_weights(scored, base, spend_col, min_fired, include_origin=include_origin)
    rows: list[dict] = []
    for info in signal_lift(scored, spend_col, include_origin):
        key = info["key"]
        b, s = base.get(key, 0), suggested.get(key, base.get(key, 0))
        if info["n_fired"] < min_fired or info["lift"] is None:
            note = "too few to tune — kept" if info["lift"] is not None else "no firings"
        elif s > b:
            note = "predicts higher spend — up"
        elif s < b:
            note = "predicts lower spend — down"
        else:
            note = "no change"
        rows.append({**info, "base_weight": b, "suggested_weight": s, "note": note})
    return rows


# ── Outcome-based calibration (associate feedback: "good call" / "not a fit") ────────────────
# Bounds are LOOSER than the spend-based ones because feedback precision is unbiased w.r.t. the
# hidden-wealth thesis (it measures confirmed good calls, not current spend).
FEEDBACK_MIN = 8          # min verdicts (fit+nofit) on a signal before it may move its weight
FB_LO, FB_HI = 0.5, 2.0


def _label_to_key() -> dict:
    """Map a signal's display label (as stored in feedback_stats) back to its key."""
    from scoring.combine import SIGNALS
    return {label: key for key, label, *_ in SIGNALS}


def feedback_lift(stats: list[dict], min_sample: int = FEEDBACK_MIN) -> list[dict]:
    """Per-signal precision (fit / (fit+nofit)) and its lift over the base good-call rate.

    ``stats`` is store.get_feedback_stats(shop): [{signal(label), fit, nofit}]. lift > 1 means
    'clients this signal flags are confirmed good calls more often than average' → up-weight.
    """
    total_fit = sum(int(s.get("fit", 0)) for s in stats)
    total = sum(int(s.get("fit", 0)) + int(s.get("nofit", 0)) for s in stats)
    base = (total_fit / total) if total else None
    rows: list[dict] = []
    for s in stats:
        fit, nofit = int(s.get("fit", 0)), int(s.get("nofit", 0))
        n = fit + nofit
        prec = (fit / n) if n else None
        lift = (prec / base) if (prec is not None and base) else None
        rows.append({"signal": s.get("signal"), "n": n,
                     "precision": round(prec, 3) if prec is not None else None,
                     "lift": round(lift, 3) if lift is not None else None})
    rows.sort(key=lambda r: (r["lift"] is not None, r["lift"] or 0), reverse=True)
    return rows


def calibrate_from_feedback(
    stats: list[dict],
    base_weights: dict[str, int] | None = None,
    min_sample: int = FEEDBACK_MIN,
    lo: float = FB_LO,
    hi: float = FB_HI,
) -> dict[str, int]:
    """Return new weights, base scaled by each signal's feedback precision lift (bounded)."""
    base = dict(base_weights or SIGNAL_WEIGHTS)
    l2k = _label_to_key()
    out = dict(base)
    for r in feedback_lift(stats, min_sample):
        key = l2k.get(r["signal"])
        if not key or key not in base or r["lift"] is None or r["n"] < min_sample:
            continue
        mult = max(lo, min(hi, r["lift"]))
        out[key] = max(1, int(round(base[key] * mult)))
    return out


def feedback_calibration_report(
    stats: list[dict],
    base_weights: dict[str, int] | None = None,
    min_sample: int = FEEDBACK_MIN,
) -> list[dict]:
    """Rows for display: precision + lift + base vs suggested weight + a plain-English note."""
    base = dict(base_weights or SIGNAL_WEIGHTS)
    suggested = calibrate_from_feedback(stats, base, min_sample)
    l2k = _label_to_key()
    rows: list[dict] = []
    for r in feedback_lift(stats, min_sample):
        key = l2k.get(r["signal"])
        b = base.get(key)
        s = suggested.get(key, b)
        if key is None or b is None:
            note = "unknown signal"
        elif r["n"] < min_sample or r["lift"] is None:
            note = "too few verdicts — kept"
        elif s > b:
            note = "confirmed good calls — up"
        elif s < b:
            note = "poor calls — down"
        else:
            note = "no change"
        rows.append({**r, "key": key, "base_weight": b, "suggested_weight": s, "note": note})
    return rows
