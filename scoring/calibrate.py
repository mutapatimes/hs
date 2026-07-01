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

This calibrates on a *snapshot* of realised spend, not on a longitudinal "did this flagged
hidden-VIC later convert" label (we don't retain that history). It is therefore a measure of
"does this signal track spending power for THIS merchant's customers", which is the right,
available proxy. Adjustments are bounded (a signal can be at most doubled or halved) and only
applied when enough customers fired the signal, so a handful of outliers can't swing a weight.

Everything here is pure and offline: it reads a frame, returns numbers / a new weights dict.
Nothing is persisted; the caller decides whether to adopt the suggested weights.
"""
from __future__ import annotations

import pandas as pd

from scoring.combine import SIGNAL_WEIGHTS, active_signals

SPEND_COL = "Spent"
# Don't move a weight unless at least this many customers fired the signal — protects
# against a couple of big spenders swinging a rarely-fired signal.
MIN_FIRED = 25
# Bound how far one calibration pass can move a weight (multiplier on the base weight).
LO, HI = 0.5, 2.0


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
