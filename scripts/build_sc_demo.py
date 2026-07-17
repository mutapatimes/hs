"""Build the Store Concierge demo desk (web/site/sc-demo.html) from sample order data.

Mirrors Halia's /demo: a committed static page so requests stay light. Recency is anchored
to the sample's most recent order so a stale sample still shows a realistic active/lapsed mix.
Run: .venv/bin/python scripts/build_sc_demo.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.loader import load_data                       # noqa: E402
from halia.storeconcierge.clienteling import clienteling_payload  # noqa: E402
from halia.storeconcierge.dashboard import render_clienteling     # noqa: E402

SRC = sys.argv[1] if len(sys.argv) > 1 else "sample_data/SAMPLE3.xlsx"
OUT = ROOT / "web" / "site" / "sc-demo.html"


def main() -> None:
    df = load_data(SRC)
    last = pd.to_datetime(df.get("Last Shopped"), errors="coerce")
    as_of = last.max() if last.notna().any() else None      # anchor "today" to the data
    payload = clienteling_payload(df, as_of=as_of, limit=250)
    OUT.write_text(render_clienteling(payload, demo=True), encoding="utf-8")
    s = payload["stats"]
    print(f"wrote {OUT}  ({s['customers']:,} customers, {s['winback']:,} win-back, "
          f"rows shown: {len(payload['customers'])})")


if __name__ == "__main__":
    main()
