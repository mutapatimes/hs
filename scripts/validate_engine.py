"""Validate the Halia engine against a merchant's own book, honestly.

The Halia score is computed from WEALTH SIGNALS ALONE and never sees spend, so we can ask a fair,
non-circular question: do the merchant's PROVEN top clients (their actual biggest spenders) score
A-grade on wealth signals alone? If yes, the engine recovers known wealth, and the hidden VICs are
the customers who carry the SAME markers but have not spent yet.

This deliberately does NOT lead with "score predicts spend" — the engine's best signals find people
who have not spent yet, so snapshot spend-lift is biased against the thesis (see scoring/calibrate.py).
Instead it reports:
  1. Grade -> spend gradient (do higher grades spend more, among all and among active clients)
  2. Top-client RECOVERY: what share of the top spenders grade A*/A, vs the base rate (enrichment)
  3. Score-decile -> median spend, with a Spearman rank correlation
  4. Signal ENRICHMENT among top clients (which wealth markers the proven VIPs actually carry)
  5. The hidden-VIC bridge: hidden VICs share the top clients' signal profile
  6. Honest limits.

Reusable on any book. Run it on the first client's real export for a client-specific pitch stat.

Usage
-----
    python scripts/validate_engine.py --data sample_data/SAMPLE3.xlsx
    python scripts/validate_engine.py --data client.xlsx --spend-col "LT Spent" --top-pct 5
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scoring.combine import SCORE_COL, active_signals, score_customers  # noqa: E402
from scoring.grading import GRADE_LABEL, tier_for, to_score100  # noqa: E402

GRADES = ["A*", "A", "B", "C"]
A_GRADES = {"A*", "A"}


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=0)
    return pd.read_csv(path)


def _fmt(x: float) -> str:
    if x >= 1_000_000:
        return f"£{x/1_000_000:.2f}m"
    if x >= 1_000:
        return f"£{x/1_000:.1f}k"
    return f"£{x:,.0f}"


def analyse(df: pd.DataFrame, spend_col: str, top_pct: float) -> dict:
    scored = score_customers(df)
    s100 = scored[SCORE_COL].map(lambda v: to_score100(float(v)))
    grade = s100.map(lambda s: GRADE_LABEL.get(tier_for(s), tier_for(s)))
    spend = pd.to_numeric(scored.get(spend_col), errors="coerce").fillna(0.0)
    n = len(scored)
    out = {"n": n, "spend_col": spend_col}

    # 1. grade -> spend
    base_med = float(spend.median())
    out["by_grade"] = []
    for g in GRADES:
        m = grade == g
        cnt = int(m.sum())
        out["by_grade"].append({
            "grade": g, "n": cnt,
            "mean": float(spend[m].mean()) if cnt else 0.0,
            "median": float(spend[m].median()) if cnt else 0.0,
        })
    out["base_median"] = base_med
    a_med = float(spend[grade.isin(A_GRADES)].median()) if grade.isin(A_GRADES).any() else 0.0
    c_med = float(spend[grade == "C"].median()) if (grade == "C").any() else 0.0
    out["a_vs_c_median_multiple"] = (a_med / c_med) if c_med else None
    out["a_vs_base_median_multiple"] = (a_med / base_med) if base_med else None

    # 2. top-client recovery
    k = max(1, int(round(n * top_pct / 100.0)))
    top_idx = spend.sort_values(ascending=False).head(k).index
    top_grade = grade.loc[top_idx]
    base_a_rate = float(grade.isin(A_GRADES).mean())
    top_a_rate = float(top_grade.isin(A_GRADES).mean())
    out["recovery"] = {
        "top_pct": top_pct, "k": k,
        "top_a_rate": top_a_rate, "base_a_rate": base_a_rate,
        "enrichment": (top_a_rate / base_a_rate) if base_a_rate else None,
        "top_grade_dist": {g: int((top_grade == g).sum()) for g in GRADES},
    }

    # 3. score decile -> median spend + Spearman
    try:
        dec = pd.qcut(s100.rank(method="first"), 10, labels=False)
        out["deciles"] = [float(spend[dec == d].median()) for d in range(10)]
    except Exception:  # noqa: BLE001
        out["deciles"] = []
    sr = pd.concat([s100, spend], axis=1).dropna()
    out["spearman"] = float(sr.corr(method="spearman").iloc[0, 1]) if len(sr) > 2 else None

    # 4. signal enrichment among top clients (active_signals() yields registry tuples; [3] = flag col)
    sig_cols = [t[3] for t in active_signals() if t[3] in scored.columns]
    top_set = set(top_idx)
    enr = []
    for c in sig_cols:
        fired = scored[c].fillna(False).astype(bool)
        base_p = float(fired.mean())
        top_p = float(fired.loc[top_idx].mean())
        if base_p > 0 and fired.sum() >= 20:
            enr.append({"signal": c, "base_prev": base_p, "top_prev": top_p,
                        "enrichment": top_p / base_p, "n_fired": int(fired.sum())})
    enr.sort(key=lambda e: e["enrichment"], reverse=True)
    out["signal_enrichment"] = enr

    # 5. hidden-VIC bridge: do hidden VICs carry the top-client markers?
    from scoring.combine import HIDDEN_COL
    if HIDDEN_COL in scored.columns:
        hidden = scored[HIDDEN_COL].fillna(False).astype(bool)
        top_sig = {e["signal"] for e in enr[:6]}
        # share of hidden VICs firing at least one of the top-client marker signals
        if top_sig:
            hv = scored.loc[hidden, list(top_sig)].fillna(False).astype(bool).any(axis=1)
            out["hidden_share_top_markers"] = float(hv.mean()) if hidden.any() else 0.0
            out["hidden_n"] = int(hidden.sum())
    return out


def report(a: dict) -> None:
    p = print
    p("=" * 68)
    p(f"HALIA ENGINE VALIDATION  ·  {a['n']:,} customers  ·  spend = {a['spend_col']}")
    p("=" * 68)
    p("\n1. GRADE -> SPEND  (score never sees spend; this is out-of-sample)")
    p(f"   {'grade':6} {'clients':>9} {'mean spend':>13} {'median spend':>14}")
    for r in a["by_grade"]:
        p(f"   {r['grade']:6} {r['n']:>9,} {_fmt(r['mean']):>13} {_fmt(r['median']):>14}")
    if a["a_vs_c_median_multiple"]:
        p(f"   -> A-grade clients spend {a['a_vs_c_median_multiple']:.1f}x the median of C-grade clients.")
    if a["a_vs_base_median_multiple"]:
        p(f"   -> A-grade median spend is {a['a_vs_base_median_multiple']:.1f}x the whole-book median.")

    r = a["recovery"]
    p(f"\n2. TOP-CLIENT RECOVERY  (top {r['top_pct']:.0f}% by spend = {r['k']:,} proven clients)")
    p(f"   {r['top_a_rate']*100:.0f}% of your proven top clients grade A*/A on wealth signals alone")
    p(f"   vs {r['base_a_rate']*100:.0f}% of the whole book  ->  {r['enrichment']:.1f}x enrichment")
    p(f"   top-client grades: " + ", ".join(f"{g} {r['top_grade_dist'][g]}" for g in GRADES))

    if a["deciles"]:
        p("\n3. SCORE DECILE -> MEDIAN SPEND  (decile 1 = lowest score, 10 = highest)")
        p("   " + "  ".join(f"{i+1}:{_fmt(v)}" for i, v in enumerate(a["deciles"])))
    if a["spearman"] is not None:
        p(f"   Spearman rank correlation (score vs spend): {a['spearman']:.3f}")

    p("\n4. WHICH WEALTH MARKERS YOUR PROVEN TOP CLIENTS CARRY  (enrichment vs base)")
    for e in a["signal_enrichment"][:12]:
        p(f"   {e['signal']:22} {e['enrichment']:>5.1f}x   "
          f"(top {e['top_prev']*100:4.1f}% vs base {e['base_prev']*100:4.1f}%, n={e['n_fired']:,})")

    if "hidden_share_top_markers" in a:
        p(f"\n5. THE HIDDEN-VIC BRIDGE")
        p(f"   {a['hidden_n']:,} hidden VICs; {a['hidden_share_top_markers']*100:.0f}% carry at least one "
          f"of the top-6 markers your proven top clients carry.")
        p("   -> same wealth fingerprint, spend not yet realised.")

    p("\n6. HONEST LIMITS")
    p("   Snapshot of one book: 'top clients' are those who ALREADY converted (survivorship).")
    p("   The score is spend-independent, so recovery is real, but the definitive test is")
    p("   longitudinal: do surfaced hidden VICs go on to become top clients? Re-run this on the")
    p("   client's own book, and feed associate verdicts back in (scoring/calibrate.py) over time.")
    p("=" * 68)


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the Halia engine against a book.")
    ap.add_argument("--data", default="sample_data/SAMPLE3.xlsx")
    ap.add_argument("--spend-col", default="LT Spent")
    ap.add_argument("--top-pct", type=float, default=5.0, help="Top N%% by spend = proven top clients")
    args = ap.parse_args()
    df = _read(Path(args.data))
    col = args.spend_col if args.spend_col in df.columns else ("Spent" if "Spent" in df.columns else args.spend_col)
    report(analyse(df, col, args.top_pct))


if __name__ == "__main__":
    main()
