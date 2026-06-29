"""Build the browser MVP: real engine output rendered in the Halia UI.

Runs the scoring engine on the local sample data, transforms the top hidden VICs
into the UI's data shape (identities MASKED), injects them into
``web/template.html``, and writes ``output/mvp.html``.

    python build_mvp.py        # then open output/mvp.html in a browser
"""
from __future__ import annotations

import json
import re
import sys

import pandas as pd

from config import OUTPUT_DIR, ROOT
from scoring.combine import (
    HIDDEN_COL,
    REASONS_COL,
    SCORE_COL,
    VIC_SPEND_THRESHOLD,
    score_customers,
    top_hidden_vics,
)
from scoring.grading import GRADE_LABEL, tier_for as _tier, to_score100 as _score100
from scoring.loader import load_data

TEMPLATE = ROOT / "web" / "template.html"
OUT = OUTPUT_DIR / "mvp.html"
# The dashboard renders ALL hidden VICs (ranked), so the filter chips / search
# reach every one — not just a top-N slice that buries weak single-signal matches.

# Recommended-approach copy, keyed by the strongest signal that fired.
RECO = {
    "Work email": "High earning potential masked by modest spend. Lead with a personal, service-led approach — recognition, not a discount.",
    "Styling service (B2B)": "B2B trade account — this buyer styles many UHNW clients. Open a wholesale/trade relationship with a dedicated contact and recurring-order terms, not a one-off discount. Highest-value relationship to win.",
    "HNWI postcode": "Ultra-prime billing area. Strong candidate for a private appointment and early access to new drops.",
    "Prime residence": "Trophy-building address signals real wealth. Worth a personal associate assignment.",
    "Delivery": "Notable delivery destination. Offer concierge / in-stay delivery and capture a primary address.",
    "GCC billing": "Gulf home market. Time outreach to their travel pattern; flag concierge delivery.",
    "Tax haven": "Offshore billing footprint — handle discreetly and lead with service.",
    "Honorific": "Titled client. Keep handling discreet and service-first.",
    "Company": "Wealth-linked employer on file. A gentle, service-led first approach.",
    "Phone": "International dialling code linked to wealth. Corroborate before heavy outreach.",
    "Rich list": "Possible public-figure name match — verify the identity before acting.",
    "Premium card": "Premium-card tell. Corroborate, then offer white-glove service.",
    "IP location": "Location tell from checkout — weak alone; watch for a second signal.",
}
DEFAULT_RECO = "A genuine hidden-VIC tell on modest current spend. Worth a personal, service-led approach."


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _display_name(name: object) -> str:
    text = str(name or "").strip()
    if not text:
        return "—"
    return text.title() if (text.islower() or text.isupper()) else text


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _num(value: object, default: float = 0.0) -> float:
    """NaN-safe numeric coercion (the export can have blank spend cells)."""
    v = pd.to_numeric(value, errors="coerce")
    return float(default if pd.isna(v) else v)


def _initials(name: object) -> str:
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# Score-to-100 and tier mapping now live in scoring/grading.py (shared with the
# real-time POS lookup), imported above as _score100 / _tier.

# Latent = projected ANNUAL value if this client is converted to a loyal client:
#     latent = max(client AOV, store AOV) x AOV-uplift x target orders/year
# Anchored to the dataset's own AOV and to widely-cited luxury-clienteling
# benchmarks (industry rules of thumb, NOT a fitted model — these are tunable):
#   - loyal luxury clients buy ~4-6x/year, multi-season     -> _LATENT_FREQ
#   - personal clienteling lifts basket size ~1.3-2x        -> _LATENT_AOV_UPLIFT
#   - stronger wealth signals (grade) => more real headroom -> both scale by grade
# A real estimate would calibrate these against the merchant's own confirmed-VIC
# outcomes; until then this is a research-anchored heuristic, not a forecast.
_LATENT_FREQ = {"A1": 6, "A": 5, "B": 4, "C": 3}            # target orders / year
_LATENT_AOV_UPLIFT = {"A1": 2.0, "A": 1.8, "B": 1.5, "C": 1.3}
_LATENT_CAP = 100_000                                       # sanity ceiling


def _store_aov(df: pd.DataFrame) -> float:
    """Blended average order value of the dataset = total spend / total orders.

    Uses 'Count of CUST_ID' as each customer's order count, ignoring missing and
    junk rows (e.g. a pivot grand-total with an absurd count).
    """
    if "Spent" not in df.columns:
        return 0.0
    spend = pd.to_numeric(df["Spent"], errors="coerce")
    if "Count of CUST_ID" not in df.columns:
        mean = spend.mean()
        return float(mean) if pd.notna(mean) else 0.0
    orders = pd.to_numeric(df["Count of CUST_ID"], errors="coerce")
    ok = spend.notna() & orders.notna() & (orders >= 1) & (orders < 200)
    total_orders = orders[ok].sum()
    if total_orders <= 0:
        mean = spend[ok].mean()
        return float(mean) if pd.notna(mean) else 0.0
    return float(spend[ok].sum() / total_orders)


def _orders(row: pd.Series) -> int:
    """Per-customer order count from 'Count of CUST_ID' (clamped sane, min 1)."""
    n = _num(row.get("Count of CUST_ID"), 1.0)
    return int(n) if 1 <= n < 200 else 1


def _latent(spend: float, orders: int, tier: str, store_aov: float) -> int:
    """Projected ANNUAL value if converted to a loyal client. NOT a model."""
    client_aov = spend / orders if orders else spend
    base_aov = max(client_aov, store_aov)
    est = base_aov * _LATENT_AOV_UPLIFT.get(tier, 1.5) * _LATENT_FREQ.get(tier, 4)
    return int(round(min(est, _LATENT_CAP), -2))           # nearest £100


def _location(row: pd.Series) -> str:
    city = str(row.get("LATEST_BILLING_ADDRESS3") or "").strip()
    zipc = str(row.get("LATEST_BILLING_ZIP") or "").strip()
    if not city:
        return "Address withheld"
    outward = zipc.split()[0] if zipc else ""
    return f"{city.title()}, {outward}" if outward else city.title()


def _city(row: pd.Series) -> str:
    city = _text(row.get("LATEST_BILLING_ADDRESS3")) or _text(row.get("LATEST_SHIPPING_ADDRESS3"))
    return city.title() if city else "—"


def _last_shopped(row: pd.Series) -> tuple[int, str]:
    """Return (sortable epoch seconds, display label) for the last order date."""
    ts = pd.to_datetime(row.get("Last Shopped"), errors="coerce")
    if pd.isna(ts):
        return 0, "—"
    return int(ts.value // 10**9), ts.strftime("%b %Y")


def _parse_signals(reasons: object, seg_labels: dict[str, str]) -> list[dict]:
    """Split the engine's 'Label: detail; Label: detail' reasons into UI chips."""
    sigs = []
    for part in str(reasons or "").split("; "):
        part = part.strip()
        if not part:
            continue
        label = part.split(": ", 1)[0]
        seg = _slug(label)
        seg_labels.setdefault(seg, label)
        sigs.append({"seg": seg, "d": part, "x": ""})
    return sigs


def _client(i: int, row: pd.Series, seg_labels: dict[str, str], store_aov: float) -> dict:
    raw = _num(row[SCORE_COL])
    s100 = _score100(raw)
    t = _tier(s100)
    spend = _num(row.get("Spent"))
    sigs = _parse_signals(row[REASONS_COL], seg_labels)
    top_label = sigs[0]["d"].split(": ", 1)[0] if sigs else ""
    last_sort, last_label = _last_shopped(row)
    return {
        "id": f"C-{i + 1:04d}",
        "init": _initials(row.get("Name")),
        "name": _display_name(row.get("Name")),
        "email": _text(row.get("EMAIL_ADDR")),
        "phone": _text(row.get("PHONE")),
        "loc": _location(row),
        "city": _city(row),
        "tier": t,
        "grade": GRADE_LABEL.get(t, t),
        "score": s100,
        "spend": int(round(spend)),
        "latent": _latent(spend, _orders(row), t, store_aov),
        "count": len(sigs),
        "last": last_label,
        "lastSort": last_sort,
        "signals": sigs,
        "reco": RECO.get(top_label, DEFAULT_RECO),
    }


def _fmt_money(v: float) -> str:
    if v >= 1_000_000:
        return f"£{v / 1_000_000:.1f}m"
    if v >= 1_000:
        return f"£{v / 1_000:.0f}k"
    return f"£{int(round(v)):,}"


def _scored_frame(source: str):
    """Return a scored per-customer frame from the chosen source.

    'shopify' pulls live from the store (Admin API), 'file' loads the local xlsx.
    Both end in the same score_customers() shape the renderer expects.
    """
    if source == "shopify":
        from halia import config as _hc  # noqa: F401 — importing loads .env
        from scoring.shopify import orders_to_customers
        from scoring.shopify_fetch import fetch_orders

        customers = orders_to_customers(fetch_orders()).rename(
            columns={"orders_count": "Count of CUST_ID"}
        )
        return score_customers(customers)
    return score_customers(load_data())


def render_dashboard(scored, head_extra: str = "") -> str:
    """Render the Halia dashboard HTML from a scored frame.

    Reused by the local build (writes a file) and the embedded Shopify app (serves it
    inside the admin). ``head_extra`` is injected into <head> — the embedded app uses it
    to add the App Bridge script so the page works inside admin.shopify.com.
    """
    hidden = scored[scored[HIDDEN_COL]].copy()
    store_aov = _store_aov(scored)
    seg_labels: dict[str, str] = {}
    top = top_hidden_vics(scored, n=max(len(hidden), 1))
    data = [_client(i, row, seg_labels, store_aov) for i, (_, row) in enumerate(top.iterrows())]
    segments = {seg: {"label": label} for seg, label in seg_labels.items()}

    hidden_count = int(len(hidden))
    latent_total = sum(
        _latent(_num(r.get("Spent")), _orders(r), _tier(_score100(_num(r[SCORE_COL]))), store_aov)
        for _, r in hidden.iterrows()
    )
    avg_spend = float(hidden["Spent"].mean()) if "Spent" in hidden and hidden_count else 0.0
    top_tier = sum(
        1 for _, r in hidden.iterrows() if _tier(_score100(float(r[SCORE_COL]))) in {"A1", "A"}
    )

    def _safe(s: str) -> str:
        return s.replace("</", "<\\/")  # keep JSON out of the </script> close

    html = TEMPLATE.read_text(encoding="utf-8")
    if head_extra:
        html = html.replace("<head>", "<head>\n" + head_extra, 1)
    html = html.replace("__SEGMENTS__", _safe(json.dumps(segments)))
    html = html.replace("__DATA__", _safe(json.dumps(data)))
    html = html.replace("__STAT_SCORED__", f"{len(scored):,}")
    html = html.replace("__STAT_LATENT__", _fmt_money(latent_total))
    html = html.replace("__STAT_COUNT__", str(hidden_count))
    html = html.replace("__STAT_AVGSPEND__", _fmt_money(avg_spend))
    html = html.replace("__STAT_TOPTIER__", str(top_tier))
    return html


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "file"
    scored = _scored_frame(source)
    html = render_dashboard(scored)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    hidden_count = int(scored[HIDDEN_COL].sum())
    print(
        f"Scored {len(scored):,} customers · {hidden_count} hidden VICs "
        f"(threshold £{VIC_SPEND_THRESHOLD:,.0f})\n"
        f"Wrote {OUT}  —  open it in a browser."
    )


if __name__ == "__main__":
    main()
