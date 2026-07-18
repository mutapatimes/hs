"""Build a sample campaign-monitoring dashboard (web/site/campaign-demo.html).

Scores SAMPLE3, targets a campaign (A-grade + work-email / Companies House clients), and
synthesises order-level sales across the campaign window (the aggregate sample has no per-order
dates) so the charts read realistically. The metrics engine + view are the real ones; only the
demo's order dates are generated. Run: .venv/bin/python scripts/build_campaign_demo.py
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scoring.loader import load_data                         # noqa: E402
from scoring.combine import score_customers                 # noqa: E402
from build_mvp import dashboard_payload                     # noqa: E402
from halia.campaigns import campaign_metrics, select_members  # noqa: E402
from halia.campaign_view import render_campaign             # noqa: E402

OUT = ROOT / "web" / "site" / "campaign-demo.html"
START, END = date(2025, 3, 1), date(2025, 5, 31)

CAMPAIGN = {
    "name": "Spring Private Preview",
    "starts": START.isoformat(), "ends": END.isoformat(),
    "config": {"tiers": ["A1", "A"], "signals": ["work-email", "companies-house", "major-employer"]},
}


def main() -> None:
    scored = score_customers(load_data("sample_data/SAMPLE3.xlsx"))
    payload = dashboard_payload(scored, {}, "sample", {"aov": 0, "max_orders": 0, "highest_lt": 0})
    clients = payload["data"]
    members = select_members(CAMPAIGN, clients)

    # Synthesise campaign-window orders: ~48% of members respond, 1-3 orders each, sized off their
    # own AOV/spend. Deterministic (seeded) so the demo is reproducible.
    rng = random.Random(42)
    span = (END - START).days
    for m in members:
        if rng.random() > 0.48:
            m["orders"] = []
            continue
        aov = float(m.get("aov") or 0) or max(400.0, float(m.get("spend") or 0) / 6 or 900.0)
        orders = []
        # seed each buyer's real last-shopped date as a prior order, so those who had gone quiet
        # before the window (>90 days) register as reactivations when they buy in-window
        ls = m.get("lastSort")
        if ls:
            try:
                orders.append({"date": date.fromtimestamp(int(ls)).isoformat(), "amount": round(aov, 2)})
            except (ValueError, OverflowError, OSError):
                pass
        for _ in range(rng.randint(1, 3)):
            d = START + timedelta(days=rng.randint(0, span))
            amt = round(aov * rng.uniform(0.6, 1.8), 2)
            orders.append({"date": d.isoformat(), "amount": amt})
        m["orders"] = orders

    metrics = campaign_metrics(CAMPAIGN, clients)
    OUT.write_text(render_campaign(metrics, demo=True), encoding="utf-8")
    k = metrics["kpis"]
    print(f"wrote {OUT}  ({k['members']} members, {k['buyers']} buyers, "
          f"£{k['revenue']:,.0f} over {len(metrics['series'])} weeks)")


if __name__ == "__main__":
    main()
