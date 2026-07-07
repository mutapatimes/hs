"""Build the browser MVP: real engine output rendered in the Halia UI.

Runs the scoring engine on the local sample data, transforms the top potential VICs
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
# The dashboard renders ALL potential VICs (ranked), so the filter chips / search
# reach every one: not just a top-N slice that buries weak single-signal matches.

# Recommended-approach copy, keyed by the strongest signal that fired.
RECO = {
    "Work email": "High earning potential masked by modest spend. Lead with a personal, service-led approach: recognition, not a discount.",
    "Styling service (B2B)": "B2B trade account: this buyer styles many UHNW clients. Open a wholesale/trade relationship with a dedicated contact and recurring-order terms, not a one-off discount. Highest-value relationship to win.",
    "HNWI postcode": "Ultra-prime billing area. Strong candidate for a private appointment and early access to new drops.",
    "Prime residence": "Trophy-building address signals real wealth. Worth a personal associate assignment.",
    "Property value": "Lives in a high-value area (local property prices well above national). A genuine wealth tell on modest spend: worth a personal, service-led approach.",
    "Prime location": "Lives in a prime area (postcode, district and local property prices all point the same way). A genuine wealth tell on modest spend: worth a personal, service-led approach.",
    "Delivery": "Notable delivery destination. Offer concierge / in-stay delivery and capture a primary address.",
    "Honorific": "Titled client. Keep handling discreet and service-first.",
    "Company": "Wealth-linked employer on file. A gentle, service-led first approach.",
    "Rich list": "Possible public-figure name match: verify the identity before acting.",
    "Premium card": "Premium-card tell. Corroborate, then offer white-glove service.",
    "IP location": "Location tell from checkout: weak alone; watch for a second signal.",
}
DEFAULT_RECO = "A genuine potential-VIC tell on modest current spend. Worth a personal, service-led approach."


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _display_name(name: object) -> str:
    text = str(name or "").strip()
    if not text:
        return "·"
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
# benchmarks (industry rules of thumb, NOT a fitted model: these are tunable):
#   - loyal luxury clients buy ~4-6x/year, multi-season     -> _LATENT_FREQ
#   - personal clienteling lifts basket size ~1.3-2x        -> _LATENT_AOV_UPLIFT
#   - stronger wealth signals (grade) => more real headroom -> both scale by grade
# A real estimate would calibrate these against the merchant's own confirmed-VIC
# outcomes; until then this is a research-anchored heuristic, not a forecast.
_LATENT_FREQ = {"A1": 6, "A": 5, "B": 4, "C": 3}            # target orders / year
_LATENT_AOV_UPLIFT = {"A1": 2.0, "A": 1.8, "B": 1.5, "C": 1.3}
_LATENT_CAP = 100_000                                       # absolute sanity ceiling
_LATENT_MULTIPLE = 12                                       # never project > ~12x a client's own value


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


def _latent(spend: float, orders: int, tier: str, store_aov: float,
            score: int = 0, benchmarks: dict | None = None) -> int:
    """Projected value of this client if nurtured into a top client.

    When the merchant has supplied benchmarks (their AOV, the most orders a single
    client has placed, and their highest lifetime client), latent is anchored to those:
    we grow this client from their current spend toward that ceiling, scaled by the
    Halia score (a 99 could realistically reach your best client; a 64 reaches ~⅔ of the
    way). Without benchmarks we fall back to the old store-AOV heuristic.
    """
    b = benchmarks or {}
    # Credibility guardrail: never project more than ~12x a client's own current value. A
    # £1,200 client scored 97 should read as "worth ~£14k if nurtured", NOT "£94k / 99% of your
    # best-ever client" — over-promised latent value is the fastest way to lose a clienteling
    # director's trust in month two. max(spend, store_aov) keeps a near-zero-spend row sensible.
    cap = max(spend, store_aov) * _LATENT_MULTIPLE
    target = max(float(b.get("highest_lt") or 0),
                 float(b.get("aov") or 0) * float(b.get("max_orders") or 0))
    if target > 0:
        latent = spend + max(0.0, target - spend) * (max(0, min(100, score)) / 100.0)
        return int(round(min(latent, target, cap), -2))
    client_aov = spend / orders if orders else spend
    base_aov = max(client_aov, store_aov)
    est = base_aov * _LATENT_AOV_UPLIFT.get(tier, 1.5) * _LATENT_FREQ.get(tier, 4)
    return int(round(min(est, _LATENT_CAP, cap), -2))      # nearest £100


def _location(row: pd.Series) -> str:
    city = str(row.get("LATEST_BILLING_ADDRESS3") or "").strip()
    zipc = str(row.get("LATEST_BILLING_ZIP") or "").strip()
    outward = zipc.split()[0] if zipc else ""
    if city:
        return f"{city.title()}, {outward}" if outward else city.title()
    # No city line, but we may still have the postcode district (which the postcode signals
    # already surface) — show that rather than claiming "Address withheld", which contradicts a
    # "HNWI postcode: W8" reason on the same client. Only truly withheld when we have neither.
    if outward:
        return outward
    return "Address withheld"


def _city(row: pd.Series) -> str:
    city = _text(row.get("LATEST_BILLING_ADDRESS3")) or _text(row.get("LATEST_SHIPPING_ADDRESS3"))
    return city.title() if city else "·"


def _postcode_bits(row: pd.Series) -> tuple[str, str]:
    """(outward, area) from the billing postcode, falling back to shipping.

    'SW10 9SJ' -> ('SW10', 'SW'). The area (the leading letters) is the key the
    dashboard map aggregates VIC concentration by. Returns ('', '') when unknown.
    """
    zipc = _text(row.get("LATEST_BILLING_ZIP")) or _text(row.get("LATEST_SHIPPING_ZIP"))
    if not zipc:
        return "", ""
    outward = zipc.upper().split()[0] if " " in zipc else zipc.upper().strip()[:-3]
    outward = outward.strip()
    area = re.match(r"[A-Z]+", outward)
    return outward, (area.group(0) if area else "")


def _last_shopped(row: pd.Series) -> tuple[int, str]:
    """Return (sortable epoch seconds, display label) for the last order date."""
    ts = pd.to_datetime(row.get("Last Shopped"), errors="coerce")
    if pd.isna(ts):
        return 0, "·"
    return int(ts.value // 10**9), ts.strftime("%b %Y")


# UI presentation only: several engine signals describe the SAME underlying fact,
# "this client lives in a prime place" (the postcode, its named area, and its property
# values are one location tell seen from three fields). The engine keeps them separate
# for scoring (they share the correlated "geo" group and decay together); here we fold
# them into ONE "Prime location" chip so a client page reads as a single location reason
# instead of five near-duplicates. Distinct-fact geo tells stay on their own: a delivery
# venue, a family-office address, and phone/address agreement are separate stories.
_LOCATION_LABELS = {
    "HNWI postcode", "US prime ZIP", "Intl prime postcode", "HNW area",
    "Home value", "Prime area", "Prime residence", "High-value area",
    "Prime residential district",
}
_LOCATION_SEG = "prime-location"
_LOCATION_LABEL = "Prime location"
_TIER_ORDER = ["Ultra-prime", "Prime", "High-value"]
_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?(\s*\d[A-Z]{2})?$", re.I)


def _place_from(detail: str) -> str:
    """A human place name out of a location reason detail, or '' if it's just a code.

    'Ultra-prime (Mayfair)' -> 'Mayfair'; 'Knightsbridge (UK)' -> 'Knightsbridge';
    'Upper West Side NY (10024)' -> 'Upper West Side NY'; 'Ultra-prime (NW7 1RW)' -> '';
    'SW1X' -> ''. Prefers the text before the parenthetical (usually the name), then the
    text inside it, rejecting bare tier words, postcodes, country codes and numbers.
    """
    head = re.sub(r"\s*\(.*\)\s*$", "", detail).strip()
    m = re.search(r"\(([^)]+)\)", detail)
    inner = m.group(1).strip() if m else ""
    for cand in (head, inner):
        if (cand and cand not in _TIER_ORDER and any(ch.isalpha() for ch in cand)
                and not _POSTCODE_RE.match(cand) and cand.upper() not in {"UK", "USA", "US"}):
            return cand
    return ""


def _postcode_from(detail: str) -> str:
    """A postcode (outward or full) mentioned in a location detail, else ''."""
    m = re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?(?:\s*\d[A-Z]{2})?\b", detail)
    return m.group(0) if m else ""


def _merge_location(details: list[tuple[str, str]], outward: str = "") -> str:
    """One concise place string from the fired location tells (strongest-first).

    Uses the named area when we have one (the meaningful part) and only falls back to a
    postcode otherwise, so we never glue a named place to an unrelated postcode (the place
    and a raw postcode can come from different address fields, e.g. billing vs shipping).
    """
    tier = ""
    for _label, d in details:
        for t in _TIER_ORDER:
            if d.startswith(t) and (not tier or _TIER_ORDER.index(t) < _TIER_ORDER.index(tier)):
                tier = t
    place = next((p for _l, d in details if (p := _place_from(d))), "")
    code = place or next((p for _l, d in details if (p := _postcode_from(d))), "") or outward
    lead = f"{tier} · " if tier else ""
    core = f"{lead}{code}" if code else (tier or "high-value area")
    n = len(details)
    return core + (f" · corroborated by {n} location tells" if n > 1 else "")


def _parse_signals(reasons: object, seg_labels: dict[str, str],
                   outward: str = "") -> list[dict]:
    """Split the engine's 'Label: detail; Label: detail' reasons into UI chips,
    folding the residential-location tells into one 'Prime location' chip."""
    sigs: list = []
    loc_details: list[tuple[str, str]] = []
    loc_pos: int | None = None
    for part in str(reasons or "").split("; "):
        part = part.strip()
        if not part:
            continue
        label, _, detail = part.partition(": ")
        if label in _LOCATION_LABELS:
            if loc_pos is None:               # reserve the strongest tell's slot (order-preserving)
                loc_pos = len(sigs)
                sigs.append(None)
            loc_details.append((label, detail))
            continue
        seg = _slug(label)
        seg_labels.setdefault(seg, label)
        sigs.append({"seg": seg, "d": part, "x": ""})
    if loc_pos is not None:
        seg_labels.setdefault(_LOCATION_SEG, _LOCATION_LABEL)
        merged = _merge_location(loc_details, outward)
        sigs[loc_pos] = {"seg": _LOCATION_SEG, "d": f"{_LOCATION_LABEL}: {merged}", "x": ""}
    return sigs


def _numeric_id(cid: object) -> str:
    """Trailing digits of a Shopify customer id ('gid://…/Customer/123' -> '123')."""
    digits = re.findall(r"\d+", str(cid or ""))
    return digits[-1] if digits else ""


def _shopify_url(shop: str | None, cid: object) -> str:
    num = _numeric_id(cid)
    if not shop or not num:
        return ""
    handle = str(shop).replace(".myshopify.com", "")
    return f"https://admin.shopify.com/store/{handle}/customers/{num}"


def _client(i: int, row: pd.Series, seg_labels: dict[str, str], store_aov: float,
            orders_by_customer: dict | None = None, shop: str | None = None,
            benchmarks: dict | None = None) -> dict:
    raw = _num(row[SCORE_COL])
    s100 = _score100(raw)
    t = _tier(s100)
    spend = _num(row.get("Spent"))
    outward, area = _postcode_bits(row)
    sigs = _parse_signals(row[REASONS_COL], seg_labels, outward)
    top_label = sigs[0]["d"].split(": ", 1)[0] if sigs else ""
    last_sort, last_label = _last_shopped(row)
    cid = row.get("CUST_ID")
    n_orders = _orders(row)
    return {
        "id": f"C-{i + 1:04d}",
        "cid": str(cid) if cid is not None and not pd.isna(cid) else "",
        "init": _initials(row.get("Name")),
        "name": _display_name(row.get("Name")),
        "email": _text(row.get("EMAIL_ADDR")),
        "phone": _text(row.get("PHONE")),
        "loc": _location(row),
        "city": _city(row),
        "outward": outward,
        "area": area,
        "tier": t,
        "grade": GRADE_LABEL.get(t, t),
        "score": s100,
        "spend": int(round(spend)),
        "latent": _latent(spend, n_orders, t, store_aov, s100, benchmarks),
        "count": len(sigs),
        "confidence": int(_num(row.get("signal_confidence"))),  # distinct evidence groups fired

        "ordersCount": n_orders,
        "aov": int(round(spend / n_orders)) if n_orders else int(round(spend)),
        "last": last_label,
        "lastSort": last_sort,
        "orders": (orders_by_customer or {}).get(str(cid), []),
        "shopifyUrl": _shopify_url(shop, cid),
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
        from halia import config as _hc  # noqa: F401: importing loads .env
        from scoring.shopify import orders_to_customers
        from scoring.shopify_fetch import fetch_orders

        customers = orders_to_customers(fetch_orders()).rename(
            columns={"orders_count": "Count of CUST_ID"}
        )
        return score_customers(customers)
    return score_customers(load_data())


def _order_status(o: dict) -> tuple[str, str]:
    """Map a REST-shaped order to (display label, category). Category drives the actions:
    new / fulfilled / refunded / cancelled."""
    woo = str(o.get("status") or "").lower()
    fin = str(o.get("financial_status") or "").lower()
    ful = str(o.get("fulfillment_status") or "").lower()
    if o.get("cancelled_at") or woo in ("cancelled", "failed") or fin == "voided":
        return ("Cancelled", "cancelled")
    if woo == "refunded" or fin in ("refunded", "partially_refunded"):
        return ("Refunded", "refunded")
    if woo == "completed" or ful == "fulfilled":
        return ("Fulfilled", "fulfilled")
    label = {"processing": "Processing", "on-hold": "On hold", "pending": "Pending"}.get(woo)
    return (label or "Unfulfilled", "new")


def _orders_list(raw_orders, score_map: dict, limit: int = 600) -> list[dict]:
    """Flat, newest-first list of orders, each joined to its client's grade/score."""
    out = []
    for o in (raw_orders or []):
        cust = o.get("customer") or {}
        cid = str(cust.get("id") if cust.get("id") is not None else (o.get("customer_id") or ""))
        sc = score_map.get(cid) or {}
        label, cat = _order_status(o)
        bill = o.get("billing_address") or {}
        name = sc.get("name") or str(bill.get("name") or "").strip() or str(o.get("email") or "").strip() or "Guest order"
        if name == "·":
            name = "Guest order"
        out.append({
            "orderId": str(o.get("id") or o.get("name") or ""),
            "date": str(o.get("created_at") or "")[:10],
            "amount": int(round(_num(o.get("total_price") if o.get("total_price") is not None else o.get("total")))),
            "status": label, "statusCat": cat,
            "items": sum(int(li.get("quantity") or 0) for li in (o.get("line_items") or [])),
            "name": name, "first": firstName_py(name),
            "email": sc.get("email") or _text(o.get("email")),
            "phone": sc.get("phone") or _text(bill.get("phone") or o.get("phone")),
            "grade": sc.get("grade", ""), "tier": sc.get("tier", ""), "score": sc.get("score", 0),
            "cid": cid,
        })
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[:limit]


def firstName_py(name: str) -> str:
    n = re.sub(r"^(sir|lady|dame|lord|hrh|hsh|the hon)\s+", "", str(name or ""), flags=re.I)
    return (n.split(" ")[0] if n.strip() else "") or "there"


def dashboard_payload(scored, orders_by_customer: dict | None = None,
                      shop: str | None = None, benchmarks: dict | None = None,
                      raw_orders: list | None = None) -> dict:
    """Compute the JSON-serialisable dashboard payload from a scored frame.

    Separated from rendering so the embedded app can compute it once during sync,
    persist it, and re-render instantly on later loads (no live re-scoring per view).
    ``orders_by_customer`` (CUST_ID -> [order summaries]) powers the in-app order
    history; ``shop`` builds per-client "open in Shopify" links.
    """
    hidden = scored[scored[HIDDEN_COL]].copy()
    store_aov = _store_aov(scored)
    seg_labels: dict[str, str] = {}
    top = top_hidden_vics(scored, n=max(len(hidden), 1))
    data = [_client(i, row, seg_labels, store_aov, orders_by_customer, shop, benchmarks)
            for i, (_, row) in enumerate(top.iterrows())]
    segments = {seg: {"label": label} for seg, label in seg_labels.items()}

    hidden_count = int(len(hidden))
    latent_total = sum(
        _latent(_num(r.get("Spent")), _orders(r), _tier(s := _score100(_num(r[SCORE_COL]))),
                store_aov, s, benchmarks)
        for _, r in hidden.iterrows()
    )
    avg_spend = float(hidden["Spent"].mean()) if "Spent" in hidden and hidden_count else 0.0
    top_tier = sum(
        1 for _, r in hidden.iterrows() if _tier(_score100(float(r[SCORE_COL]))) in {"A1", "A"}
    )

    # Every scored customer (not just potential VICs) -> grade/score, so the Orders view can rank
    # any order by its client. Keyed by CUST_ID.
    score_map: dict[str, dict] = {}
    for _, r in scored.iterrows():
        cid = r.get("CUST_ID")
        if cid is None or (isinstance(cid, float) and pd.isna(cid)):
            continue
        s100 = _score100(_num(r[SCORE_COL]))
        t = _tier(s100)
        score_map[str(cid)] = {"name": _display_name(r.get("Name")), "email": _text(r.get("EMAIL_ADDR")),
                               "phone": _text(r.get("PHONE")),
                               "grade": GRADE_LABEL.get(t, t), "tier": t, "score": s100}

    from scoring.combine import config_fingerprint

    return {
        "segments": segments, "data": data,
        "orders": _orders_list(raw_orders, score_map),
        "stat_scored": f"{len(scored):,}", "stat_latent": _fmt_money(latent_total),
        "stat_count": str(hidden_count), "stat_avgspend": _fmt_money(avg_spend),
        "stat_toptier": str(top_tier),
        "engine": config_fingerprint(),   # version + config hash — audit trail for every payload
    }


def render_payload(payload: dict, head_extra: str = "", body_extra: str = "") -> str:
    """Render the dashboard HTML from a precomputed payload (see dashboard_payload)."""
    def _safe(s: str) -> str:
        return s.replace("</", "<\\/")  # keep JSON out of the </script> close

    html = TEMPLATE.read_text(encoding="utf-8")
    if head_extra:
        html = html.replace("<head>", "<head>\n" + head_extra, 1)
    if body_extra:
        html = html.replace("</body>", body_extra + "\n</body>", 1)
    html = html.replace("__SEGMENTS__", _safe(json.dumps(payload["segments"])))
    html = html.replace("__DATA__", _safe(json.dumps(payload["data"])))
    html = html.replace("__ORDERS__", _safe(json.dumps(payload.get("orders", []))))
    html = html.replace("__STAT_SCORED__", payload["stat_scored"])
    html = html.replace("__STAT_LATENT__", payload["stat_latent"])
    html = html.replace("__STAT_COUNT__", payload["stat_count"])
    html = html.replace("__STAT_AVGSPEND__", payload["stat_avgspend"])
    html = html.replace("__STAT_TOPTIER__", payload["stat_toptier"])
    return html


def known_vips_strip(scored, n: int = 8) -> str:
    """A demo-only section: top KNOWN spenders whose evidence is also strong.

    The hidden-VIC list deliberately excludes customers already spending above the VIC
    threshold — but in a demo, showing the engine reading names the merchant can verify
    ("we understood your existing VIPs") is what makes the hidden list credible. Empty
    when no known client carries a signal. Rendered as ``body_extra`` on the SAMPLE
    pages only; the live tenant dashboard is untouched.
    """
    import html as _html

    if HIDDEN_COL not in scored.columns or "Spent" not in scored.columns:
        return ""
    known = scored[
        (~scored[HIDDEN_COL].fillna(False).astype(bool))
        & (pd.to_numeric(scored["Spent"], errors="coerce").fillna(0) >= VIC_SPEND_THRESHOLD)
        & (pd.to_numeric(scored.get("signal_count"), errors="coerce").fillna(0) >= 1)
    ].sort_values(SCORE_COL, ascending=False).head(n)
    if known.empty:
        return ""
    cards = []
    for _, r in known.iterrows():
        name = _html.escape(_display_name(r.get("Name")))
        spent = _fmt_money(_num(r.get("Spent")))
        t = _tier(_score100(_num(r[SCORE_COL])))
        grade = _html.escape(GRADE_LABEL.get(t, t))
        chips = "".join(
            f'<span style="display:inline-block;margin:2px 4px 0 0;padding:3px 9px;'
            f'border:1px solid #d9d6cd;border-radius:999px;font-size:11.5px;color:#4c4f58">'
            f'{_html.escape(reason.strip())}</span>'
            for reason in str(r.get(REASONS_COL) or "").split(";")[:3] if reason.strip()
        )
        cards.append(
            '<div style="background:#fff;border:1px solid #e4e2da;border-radius:14px;'
            'padding:14px 16px;min-width:240px;flex:1 1 240px;max-width:340px">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">'
            f'<strong style="font-size:14px;color:#1A1C22">{name}</strong>'
            f'<span style="font-size:12px;color:#7a7363;white-space:nowrap">{spent} · {grade}</span>'
            f'</div><div style="margin-top:8px">{chips}</div></div>'
        )
    return (
        '<section style="max-width:1180px;margin:28px auto 40px;padding:0 24px;'
        "font-family:'Hanken Grotesk',system-ui,sans-serif\">"
        '<h2 style="font-size:16px;color:#1A1C22;margin:0 0 4px">Known VIPs, understood</h2>'
        '<p style="font-size:13px;color:#6b6e78;margin:0 0 14px">Top spenders whose evidence '
        'the engine also reads — the same signals that surface the hidden list.</p>'
        f'<div style="display:flex;flex-wrap:wrap;gap:12px">{"".join(cards)}</div></section>'
    )


def render_dashboard(scored, head_extra: str = "") -> str:
    """Render the dashboard directly from a scored frame (local build path)."""
    return render_payload(dashboard_payload(scored), head_extra,
                          body_extra=known_vips_strip(scored))


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "file"
    scored = _scored_frame(source)
    html = render_dashboard(scored)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    hidden_count = int(scored[HIDDEN_COL].sum())
    print(
        f"Scored {len(scored):,} customers · {hidden_count} potential VICs "
        f"(threshold £{VIC_SPEND_THRESHOLD:,.0f})\n"
        f"Wrote {OUT} :  open it in a browser."
    )


if __name__ == "__main__":
    main()
