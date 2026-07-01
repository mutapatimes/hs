"""Operator tool: calibrate signal weights against a merchant's own data.

Reads a customer/order file, scores it, measures each signal's spend lift, and prints a
report plus a suggested weights dict (JSON). The suggested weights can then be adopted for
that merchant (e.g. HaliaEngine(weights=...)). Nothing is persisted by this script.

Usage
-----
    python scripts/calibrate_weights.py --data sample_data/synthetic_100k.xlsx
    python scripts/calibrate_weights.py --data customers.csv --min-fired 40 --json weights.json

See scoring/calibrate.py for the method and its honest limits (snapshot spend lift, bounded,
min-sample gated).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from config import DATA_FILE  # noqa: E402
from scoring.calibrate import MIN_FIRED, calibration_report, calibrate_weights  # noqa: E402
from scoring.combine import SIGNAL_WEIGHTS, score_customers  # noqa: E402


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DATA_FILE), help="Customer/order file (.xlsx or .csv)")
    ap.add_argument("--min-fired", type=int, default=MIN_FIRED, help="Min customers firing a signal before tuning it")
    ap.add_argument("--json", help="Also write the suggested weights dict to this JSON path")
    ap.add_argument("--include-origin", action="store_true", help="Include origin-proxy signals (needs a lawful basis)")
    args = ap.parse_args()

    path = Path(args.data)
    if not path.exists():
        raise SystemExit(f"Data file not found: {path}")

    print(f"Reading {path} …", file=sys.stderr)
    df = _read(path)
    scored = score_customers(df, include_origin=args.include_origin)

    rows = calibration_report(scored, min_fired=args.min_fired, include_origin=args.include_origin)
    hdr = f"{'signal':<20}{'fired':>7}{'£fired':>11}{'£all':>10}{'lift':>7}{'base':>6}{'new':>5}  note"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        lift = f"{r['lift']:.2f}" if r["lift"] is not None else "—"
        print(f"{r['key']:<20}{r['n_fired']:>7}{r['mean_spend_fired']:>11,.0f}"
              f"{r['mean_spend_overall']:>10,.0f}{lift:>7}{r['base_weight']:>6}{r['suggested_weight']:>5}  {r['note']}")

    suggested = calibrate_weights(scored, min_fired=args.min_fired, include_origin=args.include_origin)
    changed = {k: v for k, v in suggested.items() if v != SIGNAL_WEIGHTS.get(k)}
    print(f"\n{len(changed)} weight(s) would change: {changed or '(none)'}", file=sys.stderr)
    if args.json:
        Path(args.json).write_text(json.dumps(suggested, indent=2), encoding="utf-8")
        print(f"Wrote suggested weights to {args.json}", file=sys.stderr)
    else:
        print(json.dumps(suggested, indent=2))


if __name__ == "__main__":
    main()
