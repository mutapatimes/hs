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
import time

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
    "Work email": "High earning potential masked by modest spend. Lead with a personal, service-led approach.",
    "Styling service (B2B)": "B2B trade account: this buyer styles many UHNW clients. Open a wholesale/trade relationship with a dedicated contact and recurring-order terms. Highest-value relationship to win.",
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
# outcomes; until then this is a research-anchored heuristic.
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

    'SW10 9SJ' -> ('SW10', 'SW'). The area is the key the dashboard map aggregates VIC
    concentration by: the leading letters for a UK postcode, the 3-digit prefix for a
    US ZIP ('10005' -> '100', matching the map's ZIP3 centroids). ('', '') when unknown.
    """
    zipc = _text(row.get("LATEST_BILLING_ZIP")) or _text(row.get("LATEST_SHIPPING_ZIP"))
    if not zipc:
        return "", ""
    z = zipc.strip().upper()
    if re.fullmatch(r"\d{5}(-\d{4})?", z):          # US ZIP / ZIP+4
        return z[:5], z[:3]
    outward = z.split()[0] if " " in z else z[:-3]
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

# QA / corroboration-only tells: they help the engine confirm a score but are not
# reasons a merchant would act on or filter by, so they never become a filter chip or a
# client-facing reason. They still contribute to scoring under the hood (see combine.py).
_QA_LABELS = {"Name mismatch", "Shared phone"}
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
        if label in _QA_LABELS:               # corroboration-only: scores, but never a chip/reason
            continue
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


def _admin_url(shop: str | None, cid: object, platform: str = "shopify",
               store_url: str = "") -> str:
    """Deep link to this customer in the merchant's own admin, per platform.
    WooCommerce/BigCommerce/etc. tenants must never get a Shopify link."""
    num = _numeric_id(cid)
    if platform == "woocommerce":
        base = str(store_url or "").rstrip("/")
        if not base or not num or num == "0":       # guests have no WP user to open
            return ""
        return f"{base}/wp-admin/user-edit.php?user_id={num}"
    if platform in ("", "shopify") or str(shop or "").endswith(".myshopify.com"):
        if not shop or not num:
            return ""
        handle = str(shop).replace(".myshopify.com", "")
        return f"https://admin.shopify.com/store/{handle}/customers/{num}"
    return ""                                        # bigcommerce/centra/scayle: no deep link yet


# Behaviour bands (the RFM axis, kept OUT of the Halia score: the score measures capacity,
# the band measures current behaviour, and the gap between the two is the product).
# Luxury cadence: a client is "active" within 6 months, "cooling" to a year, "lapsed" beyond.
ACTIVE_DAYS = 180
LAPSED_DAYS = 365
SLEEPING_CAP = 200   # known VICs gone quiet appended to the payload, ranked by spend


def _band(last_sort: int, now_ts: float) -> str:
    """Behaviour band from the last dated order: active / cooling / lapsed / new (no dated order)."""
    if not last_sort:
        return "new"
    days = (now_ts - last_sort) / 86400.0
    if days <= ACTIVE_DAYS:
        return "active"
    if days <= LAPSED_DAYS:
        return "cooling"
    return "lapsed"


def _client(i: int, row: pd.Series, seg_labels: dict[str, str], store_aov: float,
            orders_by_customer: dict | None = None, shop: str | None = None,
            benchmarks: dict | None = None, carts_by_customer: dict | None = None,
            platform: str = "shopify", store_url: str = "",
            now_ts: float | None = None, known: bool = False) -> dict:
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
        "band": _band(last_sort, now_ts if now_ts is not None else time.time()),
        "known": known,   # True = a proven £5k+ client appended for the Gone quiet play
                          # (kept out of the default hidden-VIC lists and counts)
        "orders": (orders_by_customer or {}).get(str(cid), []),
        "cart": (carts_by_customer or {}).get(str(cid)),   # open basket (abandoned checkout), if any
        "adminUrl": _admin_url(shop, cid, platform, store_url),   # deep link into the merchant's own admin
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

    'shopify' pulls live from the store (Admin API), 'file' loads the configured local
    xlsx, and a path ending in .xlsx loads that file (e.g. sample_data/SAMPLE3.xlsx).
    All end in the same score_customers() shape the renderer expects.
    """
    if source == "shopify":
        from halia import config as _hc  # noqa: F401: importing loads .env
        from scoring.shopify import orders_to_customers
        from scoring.shopify_fetch import fetch_orders

        customers = orders_to_customers(fetch_orders()).rename(
            columns={"orders_count": "Count of CUST_ID"}
        )
        return score_customers(customers)
    if source.lower().endswith(".xlsx"):
        return score_customers(load_data(source))
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


def _display_order_id(o: dict) -> str:
    """A clean order number for the UI (which prefixes it with '#'). Prefer Shopify's friendly
    order name ('#1001' -> '1001'); otherwise strip a gid to its trailing id
    ('gid://shopify/Order/7073010549026' -> '7073010549026'); never show the raw gid."""
    nm = str(o.get("order_name") or "").strip().lstrip("#")
    if nm:
        return nm
    raw = str(o.get("id") or o.get("name") or "").strip()
    return raw.rsplit("/", 1)[-1] if raw else ""


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
            "orderId": _display_order_id(o),
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
                      raw_orders: list | None = None,
                      carts_by_customer: dict | None = None,
                      platform: str = "shopify", store_url: str = "") -> dict:
    """Compute the JSON-serialisable dashboard payload from a scored frame.

    Separated from rendering so the embedded app can compute it once during sync,
    persist it, and re-render instantly on later loads (no live re-scoring per view).
    ``orders_by_customer`` (CUST_ID -> [order summaries]) powers the in-app order
    history; ``shop`` builds per-client "open in Shopify" links.
    """
    now_ts = time.time()
    hidden = scored[scored[HIDDEN_COL]].copy()
    store_aov = _store_aov(scored)
    seg_labels: dict[str, str] = {}
    top = top_hidden_vics(scored, n=max(len(hidden), 1))
    data = [_client(i, row, seg_labels, store_aov, orders_by_customer, shop, benchmarks,
                    carts_by_customer, platform, store_url, now_ts=now_ts)
            for i, (_, row) in enumerate(top.iterrows())]

    # --- Wealth x behaviour plays -----------------------------------------------------------
    # The behaviour axis (RFM) stays OUT of the Halia score; it is crossed with the score here,
    # at presentation time. Vectorised over the whole book (cheap: one datetime parse per column).
    spend_s = (pd.to_numeric(scored["Spent"], errors="coerce").fillna(0.0)
               if "Spent" in scored.columns else pd.Series(0.0, index=scored.index))
    last_dt = (pd.to_datetime(scored["Last Shopped"], errors="coerce")
               if "Last Shopped" in scored.columns else pd.Series(pd.NaT, index=scored.index))
    epoch_s = last_dt.map(lambda t: 0 if pd.isna(t) else int(t.value // 10**9))
    band_s = epoch_s.map(lambda e: _band(e, now_ts))
    tier_a = scored[SCORE_COL].map(lambda v: _tier(_score100(_num(v)))).isin({"A1", "A"})
    ordn_s = (pd.to_numeric(scored["Count of CUST_ID"], errors="coerce").fillna(1)
              if "Count of CUST_ID" in scored.columns else pd.Series(1, index=scored.index))
    ordn_s = ordn_s.where((ordn_s >= 1) & (ordn_s < 200), 1)

    # Gone quiet: proven £5k+ clients with strong wealth signals whose orders stopped. They sit
    # outside the hidden-VIC gate (their spend is known), so they are appended here flagged
    # known=True; the UI keeps them out of the default lists and shows them under the play.
    sleeping_mask = ((spend_s >= VIC_SPEND_THRESHOLD) & tier_a
                     & band_s.isin(["cooling", "lapsed"]))
    sleeping = scored[sleeping_mask].sort_values("Spent", ascending=False).head(SLEEPING_CAP)
    data += [_client(len(data) + j, row, seg_labels, store_aov, orders_by_customer, shop,
                     benchmarks, carts_by_customer, platform, store_url,
                     now_ts=now_ts, known=True)
             for j, (_, row) in enumerate(sleeping.iterrows())]
    segments = {seg: {"label": label} for seg, label in seg_labels.items()}

    landscape = {
        "sleeping": {"n": int(sleeping_mask.sum()),
                     "value": int(spend_s[sleeping_mask].sum())},
        "active": {"n": int((tier_a & (band_s == "active")).sum())},
        "regulars": {"n": int((~tier_a & (band_s == "active") & (ordn_s >= 4)).sum())},
    }

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

    landscape["hidden"] = {"n": hidden_count, "value": int(latent_total)}

    return {
        "segments": segments, "data": data, "platform": platform,
        "orders": _orders_list(raw_orders, score_map),
        "landscape": landscape,   # wealth x behaviour play counts over the whole book
        "stat_scored": f"{len(scored):,}", "stat_latent": _fmt_money(latent_total),
        "stat_count": str(hidden_count), "stat_avgspend": _fmt_money(avg_spend),
        "stat_toptier": str(top_tier),
        "full_history": True,   # capped to a recent window for un-upgraded tenants (see cap_payload_recent)
        "engine": config_fingerprint(),   # version + config hash — audit trail for every payload
    }


def cap_payload_recent(payload: dict, days: int = 30) -> dict:
    """Server-side entitlement gate: restrict a payload to the last ``days`` of activity for
    un-upgraded tenants (the full history is a paid feature). Clients are kept when they last
    shopped inside the window; orders by their date. Headline stats are recomputed from the
    capped set so the view is self-consistent, and full_history=False tells the UI to lock the
    longer date-range presets. Scoring still runs on full history server-side; only the viewable
    lists are trimmed here."""
    import datetime as _dt
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    cut_epoch, cut_date = cutoff.timestamp(), cutoff.strftime("%Y-%m-%d")
    full_data = payload.get("data") or []
    full_latent = sum(c.get("latent") or 0 for c in full_data)
    data = [c for c in full_data if (c.get("lastSort") or 0) >= cut_epoch]
    orders = [o for o in (payload.get("orders") or []) if str(o.get("date") or "") >= cut_date]
    latent = sum(c.get("latent") or 0 for c in data)
    spend = sum(c.get("spend") or 0 for c in data)
    toptier = sum(1 for c in data if c.get("grade") in ("A*", "A"))
    out = dict(payload)
    out.update({
        "data": data, "orders": orders,
        "stat_count": str(len(data)), "stat_latent": _fmt_money(latent),
        "stat_avgspend": _fmt_money(spend / len(data) if data else 0),
        "stat_toptier": str(toptier),
        "full_history": False, "history_days": days,
        "locked_count": len(full_data) - len(data),          # clients held back by the paywall
        "locked_latent": _fmt_money(full_latent - latent),   # their latent value, as a teaser
    })
    return out


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
    # World-map geometry (land outlines + US ZIP3 centroids) — committed open-data geometry,
    # built by scripts/build_world_map.py. No PII; the same blob for every tenant.
    html = html.replace("__WORLD__", _safe((ROOT / "web" / "world_map.json").read_text(encoding="utf-8").strip()))
    html = html.replace("__ORDERS__", _safe(json.dumps(payload.get("orders", []))))
    html = html.replace("__LANDSCAPE__", _safe(json.dumps(payload.get("landscape", {}))))
    # The demo line only ever appears on the local sample build; a live tenant's footer
    # explains latent value and nothing else.
    html = html.replace("__FOOT_DEMO__",
                        "Real output from the Halia engine on <b>sample data</b>, a fictional "
                        "store; scores are provisional. " if payload.get("demo") else "")
    html = html.replace("__STAT_SCORED__", payload["stat_scored"])
    html = html.replace("__STAT_LATENT__", payload["stat_latent"])
    html = html.replace("__STAT_COUNT__", payload["stat_count"])
    html = html.replace("__STAT_AVGSPEND__", payload["stat_avgspend"])
    html = html.replace("__STAT_TOPTIER__", payload["stat_toptier"])
    html = html.replace("__PLATFORM__", str(payload.get("platform", "shopify")))
    html = html.replace("__FULL_HISTORY__", "true" if payload.get("full_history", True) else "false")
    html = html.replace("__LOCKED_COUNT__", str(payload.get("locked_count", 0)))
    html = html.replace("__LOCKED_LATENT__", _safe(json.dumps(payload.get("locked_latent", ""))))
    return html


# Demo-only open baskets: the live app pulls real abandoned checkouts from Shopify, but the
# sample/xlsx path has none, so we synthesise a few so the drawer's "Open basket" panel and the
# Overview alert are visible in output/mvp.html. Deterministic (keyed off row position), demo-only.
_SAMPLE_BASKETS = [
    ([("Cashmere overcoat", 1, 1450), ("Silk scarf", 1, 320)], 2),
    ([("Leather weekender bag", 1, 2200)], 1),
    ([("18ct gold hoop earrings", 1, 3800), ("Gift wrapping", 1, 15)], 4),
    ([("Eau de parfum, 100ml", 2, 260)], 1),
    ([("Tailored wool blazer", 1, 890), ("Oxford shirt", 2, 190)], 3),
    ([("Grand cru case (6 bottles)", 1, 1680)], 5),
    ([("Alligator watch strap", 1, 240)], 6),
    ([("Silk evening gown", 1, 1950)], 2),
]


def _sample_carts(scored, n: int = 8) -> dict:
    """Assign a plausible open basket to the top-N surfaced hidden VICs (demo only)."""
    if HIDDEN_COL not in scored.columns:
        return {}
    top = top_hidden_vics(scored, n=n)
    base = pd.Timestamp("2026-07-08")
    carts: dict[str, dict] = {}
    for i, (_, row) in enumerate(top.iterrows()):
        cid = row.get("CUST_ID")
        if cid is None or pd.isna(cid):
            continue
        items, days_ago = _SAMPLE_BASKETS[i % len(_SAMPLE_BASKETS)]
        value = sum(q * u for _t, q, u in items)
        carts[str(cid)] = {
            "cid": str(cid),
            "value": int(value),
            "count": sum(q for _t, q, _u in items),
            "items": [{"title": t, "qty": q} for t, q, _u in items],
            "started": (base - pd.Timedelta(days=days_ago)).strftime("%Y-%m-%d"),
            "url": "",
        }
    return carts


def render_dashboard(scored, head_extra: str = "") -> str:
    """Render the dashboard directly from a scored frame (local build path)."""
    payload = dashboard_payload(scored, carts_by_customer=_sample_carts(scored))
    payload["demo"] = True   # local sample build: the footer carries the demo note
    return render_payload(payload, head_extra)


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
