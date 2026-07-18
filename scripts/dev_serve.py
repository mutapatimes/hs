"""Local dev server: the REAL Halia app, seeded with a signed-in session on SAMPLE3 data,
so the dashboard (incl. the Campaigns tab: create -> add clients -> monitor) works end to end
without a connected store. Not for production. Run: .venv/bin/python scripts/dev_serve.py
then open the printed URL.
"""
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("DATABASE_URL", None)              # force local sqlite
os.environ.setdefault("HALIA_FREE_SHOPS", "dev-store")   # full dashboard even if billing is on

from halia.api.app import app                     # noqa: E402
from halia.api import shopify_auth                # noqa: E402
from halia.api.tenant_auth import hash_token      # noqa: E402
from halia.cache import cache                     # noqa: E402
from scoring.loader import load_data              # noqa: E402
from scoring.combine import score_customers       # noqa: E402
from build_mvp import dashboard_payload           # noqa: E402
from halia.engine import engine                   # noqa: E402

SHOP, TOK, PORT = "dev-store", "devtoken", 8899


def _seed():
    store = shopify_auth.shop_store()
    store.create_tenant(SHOP, "shopify", "Dev Store (sample)", hash_token(TOK))
    scored = score_customers(load_data("sample_data/SAMPLE3.xlsx"))
    results = engine.results_from_scored(scored)
    payload = dashboard_payload(scored, {}, SHOP, {"aov": 0, "max_orders": 0, "highest_lt": 0})

    # Synthesise recent order history per client so any campaign window shows real charts (the
    # aggregate sample has no per-order dates). Each buyer also keeps their real last-shopped date
    # as a prior order, so gone-quiet -> active reactivations register.
    rng = random.Random(7)
    today = date.today()
    for c in payload["data"]:
        aov = float(c.get("aov") or 0) or max(400.0, float(c.get("spend") or 0) / 6 or 900.0)
        orders = []
        ls = c.get("lastSort")
        if ls:
            try:
                orders.append({"date": date.fromtimestamp(int(ls)).isoformat(), "amount": round(aov, 2)})
            except (ValueError, OverflowError, OSError):
                pass
        if rng.random() < 0.6:
            for _ in range(rng.randint(1, 3)):
                d = today - timedelta(days=rng.randint(0, 150))
                orders.append({"date": d.isoformat(), "amount": round(aov * rng.uniform(0.6, 1.8), 2)})
        c["orders"] = orders

    cache.set(SHOP, results, payload, [])
    return len(payload["data"])


def main() -> None:
    n = _seed()
    url = f"http://127.0.0.1:{PORT}/app?t={TOK}"
    print("\n" + "=" * 66)
    print(f"  Halia dev server — {n:,} sample clients loaded, signed in.")
    print(f"  Open:  {url}")
    print("  Campaigns tab: create a campaign, then tick clients on the Clients")
    print("  tab and 'Add to campaign', then Open monitor. Ctrl-C to stop.")
    print("=" * 66 + "\n")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
