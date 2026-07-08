"""Console dashboard — a cross-tenant birds-eye view for you.

A single authenticated page (`/console`) that answers "how many clients do we have, what happened
this week, is anything down." It reads:
  - config/connection data straight from the secret store (clients, integrations, billing), and
  - activity from the aggregate `metrics` counter table (scans, emails sent, actions, POS lookups),
    which is per-shop + per-ISO-week and holds NO customer data (see halia.store).

Gated by HALIA_ADMIN_KEY's sibling, HALIA_CONSOLE_KEY, via a signed expiring cookie — the same proven
pattern as the /admin CMS (halia/api/content.py), but an isolated credential because this surface
exposes business metrics across every tenant. Unset -> /console is disabled.
"""
from __future__ import annotations

import hashlib
import hmac
import html as _html
import re
import time

from fastapi import Body, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from halia import config
from halia.api import staff_auth
from halia.api.shopify_auth import shop_store
from halia.api.tenant_auth import _secret
from halia.store import recent_weeks

_CONSOLE_COOKIE = "halia_console"

# Human labels for the metric keys recorded across the app (see the instrumentation call sites).
_ACTION_PREFIX = "action_"
_METRIC_LABELS = {
    "scan": "Scans run",
    "customers_scanned": "Customers scanned",
    "hidden_vics": "Hidden VICs surfaced",
    "email": "Emails sent",
    "notify_slack": "Slack alerts",
    "notify_push": "Push alerts",
    "pos_lookup": "POS lookups",
}


# ── auth (signed, expiring cookie; isolated from the CMS admin key) ───────────────
def _sign(exp: int) -> str:
    return hmac.new(_secret(), f"console|{exp}".encode(), hashlib.sha256).hexdigest()


def _make_cookie(ttl: int = 60 * 60 * 12) -> str:
    exp = int(time.time()) + ttl
    return f"{exp}|{_sign(exp)}"


def _console_ok(request: Request) -> bool:
    if not config.CONSOLE_KEY:
        return False
    if staff_auth.session_ok(request):        # shared single sign-on (also set by the CMS)
        return True
    raw = request.cookies.get(_CONSOLE_COOKIE) or ""
    try:
        exp_s, sig = raw.split("|", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    return exp >= int(time.time()) and hmac.compare_digest(sig, _sign(exp))


# ── data assembly ────────────────────────────────────────────────────────────────
def _dashboard_data() -> dict:
    """Everything the console view renders. All aggregate; no customer data."""
    from halia.api.app import system_status  # lazy: app imports this module at startup

    store = shop_store()
    weeks = recent_weeks(8)
    this_week = weeks[-1]

    by_kind = store.count_tenants_by_kind()
    tenants = store.all_tenants()
    tenant_shops = {t["shop"] for t in tenants}
    all_shops = store.all_shops()
    # A pure embedded install lives in `shops` without a `tenants` row — count it as a client too.
    shop_only = [s for s in all_shops if s not in tenant_shops]
    total_clients = len(tenant_shops) + len(shop_only)

    week_totals = store.metric_totals([this_week])
    all_totals = store.metric_totals()

    def _actions(totals: dict[str, int]) -> int:
        return sum(v for k, v in totals.items() if k.startswith(_ACTION_PREFIX))

    by_shop_week = store.metric_by_shop([this_week])
    billing_map = store.billing_by_shop()
    integ_map = store.integrations_by_shop()
    feedback_map = store.feedback_by_shop()
    labels = {t["shop"]: t["label"] for t in tenants}
    kinds = {t["shop"]: t["kind"] for t in tenants}

    # Rows for every client we know of AND any shop with activity this week (so nothing that
    # happened is invisible), minus the '_system' bucket used for console/lifecycle emails.
    row_shops = (tenant_shops | set(all_shops) | set(by_shop_week)) - {"_system"}
    rows = []
    for shop in sorted(row_shops):
        m = by_shop_week.get(shop, {})
        fb = feedback_map.get(shop, {"fit": 0, "nofit": 0})
        rows.append({
            "shop": shop,
            "label": labels.get(shop) or shop,
            "kind": kinds.get(shop) or ("shopify" if shop in set(all_shops) else "—"),
            "billing": billing_map.get(shop, "—"),
            "integrations": integ_map.get(shop, []),
            "scans": m.get("scan", 0),
            "customers": m.get("customers_scanned", 0),
            "hidden": m.get("hidden_vics", 0),
            "emails": m.get("email", 0),
            "actions": sum(v for k, v in m.items() if k.startswith(_ACTION_PREFIX)),
            "fit": fb["fit"],
            "nofit": fb["nofit"],
        })
    rows.sort(key=lambda r: (r["scans"] + r["actions"] + r["emails"]), reverse=True)

    # Estimated MRR: active-ish subscriptions x configured monthly price (best-effort, labelled).
    billing = store.billing_breakdown()
    from halia.api.billing import _ACTIVE
    active_paying = sum(n for s, n in billing.items() if s in {"active", "trialing", "complete"})
    from halia.console_config import console_setting
    ccy = console_setting("plan_currency", "GBP")
    mrr = None
    price = _plan_price()
    if price is not None:
        mrr = round(active_paying * price)

    return {
        "status": system_status(),
        "clients": {
            "total": total_clients,
            "by_kind": by_kind,
            "shop_only": len(shop_only),
            "new_this_week": store.new_tenants(this_week),
        },
        "billing": {"breakdown": billing,
                    "active": sum(n for s, n in billing.items() if s in _ACTIVE),
                    "mrr_estimate": mrr, "currency": ccy},
        "integrations": store.integration_counts(),
        "subscribers": store.count_subscribers(),
        "push_subs": store.count_push_subs(),
        "week": this_week,
        "activity_week": {
            "scans": week_totals.get("scan", 0),
            "customers": week_totals.get("customers_scanned", 0),
            "hidden": week_totals.get("hidden_vics", 0),
            "emails": week_totals.get("email", 0),
            "actions": _actions(week_totals),
            "pos": week_totals.get("pos_lookup", 0),
        },
        "activity_all": {
            "scans": all_totals.get("scan", 0),
            "emails": all_totals.get("email", 0),
            "actions": _actions(all_totals),
        },
        "trends": {
            "weeks": weeks,
            "scans": list(store.metric_weekly("scan", weeks).values()),
            "emails": list(store.metric_weekly("email", weeks).values()),
        },
        "tenants": rows,
    }


def _plan_price() -> float | None:
    """The monthly plan price (whole units): the console's manual override, else live from Stripe.

    Uses the same REST helper as the rest of billing (the stripe SDK is not a dependency).
    Best-effort — returns None when neither is available.
    """
    from halia.console_config import console_setting
    manual = console_setting("plan_price", None)
    if manual not in (None, "", 0):
        try:
            return float(manual)
        except (TypeError, ValueError):
            pass
    if not (config.STRIPE_SECRET_KEY and config.STRIPE_PRICE_ID):
        return None
    try:
        from halia.api.billing import _stripe
        price = _stripe("GET", f"prices/{config.STRIPE_PRICE_ID}")
        amount = (price.get("unit_amount") or 0) / 100.0
        return amount if amount > 0 else None
    except Exception:  # pragma: no cover - network optional; the tile just hides
        return None


# ── clients + revenue ────────────────────────────────────────────────────────────
def _iter_clients() -> list[dict]:
    """Every client (tenant + embedded-only shop), with label/kind/contact email/billing.

    Shared by the Revenue and Outreach pages. Sentinel keys (_console/_system) are excluded.
    """
    from halia.api.settings import settings_for
    from halia.console_config import is_console_shop

    store = shop_store()
    tenants = {t["shop"]: t for t in store.all_tenants()}
    shops = set(store.all_shops())
    billing_map = store.billing_by_shop()
    out = []
    for shop in sorted(set(tenants) | shops):
        if is_console_shop(shop):
            continue
        t = tenants.get(shop)
        s = settings_for(shop)
        email = s.get("account_email", "") or (s.get("notify_emails") or [""])[0]
        out.append({
            "shop": shop,
            "label": (t["label"] if t else "") or shop,
            "kind": (t["kind"] if t else ("shopify" if shop in shops else "—")),
            "email": email,
            "billing": billing_map.get(shop, "—"),
        })
    return out


def _ts_date(ts) -> str | None:
    """Unix timestamp -> 'YYYY-MM-DD' (UTC), or None."""
    if not ts:
        return None
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(int(ts), _dt.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


_REV_CACHE: dict = {}


def _mrr_projection(paying: list[dict], months: int = 12) -> tuple[list[float], list[str]]:
    """Expected MRR for the next ``months``: current subscriptions carried forward, minus any
    scheduled to cancel at their renewal. An honest forward projection (we hold no MRR history)."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    series, labels = [], []
    for m in range(months):
        horizon = now + _dt.timedelta(days=30 * m)
        total = 0.0
        for c in paying:
            if c.get("cancel") and c.get("renewal"):
                try:
                    end = _dt.datetime.fromisoformat(c["renewal"]).replace(tzinfo=_dt.timezone.utc)
                    if end <= horizon:
                        continue  # cancelled subscription has lapsed by this month
                except ValueError:
                    pass
            total += c["monthly"]
        series.append(round(total, 2))
        labels.append(horizon.strftime("%b"))
    return series, labels


def _revenue_data(force: bool = False) -> dict:
    """Per-client MRR / renewal / next-payment: live from Stripe where a subscription exists,
    else the console's manual override. Cached ~10 min so a page view isn't N Stripe calls."""
    import time as _time

    from halia.api import billing
    from halia.console_config import console_settings

    if not force and _REV_CACHE.get("exp", 0) > _time.time():
        return _REV_CACHE["data"]

    st = console_settings()
    base_ccy = (st.get("plan_currency") or "GBP").upper()
    overrides = st.get("revenue_overrides") or {}
    enabled = billing.billing_enabled()

    clients = []
    for c in _iter_clients():
        shop = c["shop"]
        row = {**c, "amount": 0.0, "monthly": 0.0, "currency": base_ccy, "interval": "month",
               "renewal": None, "status": c["billing"], "source": "none", "cancel": False}
        sub = billing._subscription(shop) if enabled else None
        if sub:
            try:
                item = (sub.get("items", {}).get("data") or [{}])[0]
                price = item.get("price") or {}
                row["amount"] = (price.get("unit_amount") or 0) / 100.0
                row["currency"] = (price.get("currency") or base_ccy).upper()
                row["interval"] = (price.get("recurring") or {}).get("interval", "month")
                row["renewal"] = _ts_date(sub.get("current_period_end"))
                row["status"] = sub.get("status") or row["status"]
                row["cancel"] = bool(sub.get("cancel_at_period_end"))
                row["source"] = "stripe"
            except Exception:  # noqa: BLE001 - defensive parse
                pass
        ov = overrides.get(shop)
        if row["source"] != "stripe" and ov:
            try:
                row["amount"] = float(ov.get("amount") or 0)
            except (TypeError, ValueError):
                row["amount"] = 0.0
            row["currency"] = (ov.get("currency") or base_ccy).upper()
            row["interval"] = ov.get("interval", "month")
            row["renewal"] = ov.get("renewal_date") or None
            row["status"] = ov.get("status") or "manual"
            row["source"] = "manual"
        row["monthly"] = row["amount"] / 12 if row["interval"] == "year" else row["amount"]
        clients.append(row)

    paying = [c for c in clients if c["monthly"] > 0]
    mrr = round(sum(c["monthly"] for c in paying), 2)
    renewals = sorted([c for c in clients if c["renewal"]], key=lambda c: c["renewal"])
    trend, labels = _mrr_projection(paying)

    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date()
    incoming_30d = 0.0
    for c in renewals:
        try:
            d = _dt.date.fromisoformat(c["renewal"])
            if 0 <= (d - today).days <= 30:
                incoming_30d += c["amount"]
        except ValueError:
            pass

    # Revenue mix by billing status (monthly value).
    mix: dict[str, float] = {}
    for c in paying:
        mix[c["status"]] = mix.get(c["status"], 0.0) + c["monthly"]

    data = {
        "enabled": enabled,
        "currency": base_ccy,
        "mrr": mrr,
        "arr": round(mrr * 12, 2),
        "clients": clients,
        "paying": len(paying),
        "renewals": renewals,
        "incoming_30d": round(incoming_30d, 2),
        "next_payment": renewals[0] if renewals else None,
        "mix": sorted(mix.items(), key=lambda kv: -kv[1]),
        "trend": trend,
        "trend_labels": labels,
    }
    _REV_CACHE["data"] = data
    _REV_CACHE["exp"] = _time.time() + 600
    return data


# ── rendering (server-side; brand tokens; inline-SVG sparklines, no chart lib) ───
_CSS = """
:root{--pri:#00a1ff;--pri-d:#0081cc;--pri-sub:#d9f1ff;--ink:#111c2d;--mut:#5a6a85;
--mut2:#7c8fac;--bg:#f8fafd;--card:#fff;--line:#e4ebf0;--line2:#eef2f7;--rad:16px;
--radlg:24px;--sh:0 1px 4px 0 rgba(133,146,173,.22);--sh2:7px 7px 18px rgba(17,28,45,.04)}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--mut);
font-family:Inter,-apple-system,system-ui,sans-serif;font-size:14px;line-height:1.55;
-webkit-font-smoothing:antialiased}
a{color:var(--pri);text-decoration:none}
h1,h3{color:var(--ink);font-weight:600}
.app{display:flex;min-height:100vh}
.side{width:250px;flex:none;background:var(--card);border-right:1px solid var(--line);
padding:22px 16px;position:sticky;top:0;height:100vh;overflow-y:auto;box-shadow:var(--sh2)}
.sidelogo{display:flex;align-items:center;gap:9px;font-size:22px;font-weight:700;color:var(--ink);padding:4px 8px 0}
.sidelogo .as{color:var(--pri);font-size:23px}
.sidecap{font:600 11px Inter;letter-spacing:.16em;text-transform:uppercase;color:var(--mut2);padding:5px 10px 18px}
.nav{display:flex;flex-direction:column;gap:3px}
.nav a{display:flex;align-items:center;gap:12px;font:500 14px Inter;color:var(--mut);padding:11px 15px;border-radius:30px}
.nav a .ic{width:8px;height:8px;border-radius:50%;background:currentColor;opacity:.4;flex:none}
.nav a:hover{color:var(--pri)}
.nav a.on{background:var(--pri-sub);color:var(--pri);font-weight:600}
.nav a.on .ic{opacity:1}
.nav .signout{margin-top:14px;color:var(--mut2)}
.main{flex:1;min-width:0;padding:26px 34px 90px}
.inner{max-width:1180px;margin:0 auto}
.tophdr{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:24px}
.tophdr h1{font-size:24px;margin:0}
.topright{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.authwrap{max-width:460px;margin:9vh auto;padding:0 22px}
.sub{color:var(--mut2);font-size:13.5px;margin:3px 0 0}
.bar{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:22px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:middle}
.ok{background:#00ceb6}.warn{background:#ffae1f}
.pill{font:600 12px Inter;color:var(--ink);background:var(--card);border:1px solid var(--line);
border-radius:30px;padding:7px 14px;box-shadow:var(--sh)}
.sec{font:600 11px Inter;letter-spacing:.14em;text-transform:uppercase;color:var(--mut2);margin:32px 0 14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(186px,1fr));gap:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:var(--rad);padding:18px;box-shadow:var(--sh)}
.tile .k{font:600 11px Inter;letter-spacing:.05em;text-transform:uppercase;color:var(--mut2)}
.tile .v{font:700 28px Inter;line-height:1.1;color:var(--ink);margin-top:8px}
.tile .d{color:var(--mut);font-size:12.5px;margin-top:5px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.two{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--rad);padding:20px;box-shadow:var(--sh)}
.card h3{font:600 15px Inter;margin:0 0 14px}
.spark{width:100%;height:54px;display:block}
.row{display:flex;justify-content:space-between;align-items:center;padding:9px 0;
border-top:1px solid var(--line2);font-size:14px}.row:first-of-type{border-top:0}
.mut{color:var(--mut2)}
.tag{font:600 11px Inter;color:var(--pri);background:var(--pri-sub);border-radius:6px;padding:2px 7px;margin-right:4px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font:600 11px Inter;letter-spacing:.05em;text-transform:uppercase;
color:var(--mut2);padding:11px 12px;border-bottom:1px solid var(--line)}
td{padding:11px 12px;border-bottom:1px solid var(--line2);vertical-align:top;color:var(--ink)}
tr:hover td{background:var(--bg)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.ib{display:inline-block;font:600 11px Inter;color:var(--mut);background:var(--line2);
border-radius:6px;padding:2px 7px;margin:0 3px 3px 0}
.scroll{overflow-x:auto}
.btn{display:inline-flex;align-items:center;gap:8px;font:600 14px Inter;padding:10px 20px;
border-radius:30px;border:1px solid var(--pri);background:var(--pri);color:#fff;cursor:pointer;text-decoration:none}
.btn:hover{background:var(--pri-d);border-color:var(--pri-d)}
.btn.ghost{background:transparent;color:var(--mut);border-color:var(--line)}
.btn.ghost:hover{color:var(--pri);border-color:var(--pri)}
input[type=password]{border:1px solid var(--line);border-radius:9px;padding:12px 14px;
font:15px Inter;min-width:240px;background:var(--card);color:var(--ink)}
.shot{background:var(--card);border:1px solid var(--line);border-radius:var(--radlg);
padding:28px 30px;box-shadow:var(--sh)}
.shot .mark{color:var(--pri);font-size:22px;font-weight:700}
.shot .big{font:700 46px Inter;line-height:1;color:var(--ink);margin:8px 0 3px}
.shot .cap{color:var(--mut);font-size:13.5px}
.shot .stamp{color:var(--mut2);font-size:11.5px;text-transform:uppercase;letter-spacing:.12em;margin-top:16px}
.shotrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-top:16px}
.shotrow .n{font:700 26px Inter;color:var(--ink)}
.shotrow .l{color:var(--mut);font-size:12px;margin-top:2px}
.chart{width:100%;height:auto;display:block}
.f{margin:0 0 15px}
.f label{display:block;font:600 12px Inter;color:var(--ink);margin-bottom:6px}
.f input,.f select,.f textarea{width:100%;border:1px solid var(--line);border-radius:9px;
padding:10px 13px;font:14px Inter;background:var(--card);color:var(--ink)}
.f input:focus,.f select:focus,.f textarea:focus{outline:0;border-color:var(--pri);box-shadow:0 0 0 3px rgba(0,161,255,.18)}
.f textarea{min-height:120px;font-family:ui-monospace,Menlo,monospace;font-size:13px;resize:vertical}
.f .hint{color:var(--mut2);font-size:12px;margin-top:5px}
.save{position:sticky;bottom:0;background:linear-gradient(transparent,var(--bg) 45%);padding:22px 0 6px;margin-top:10px}
.stabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:22px;overflow-x:auto}
.stabs a{font:600 12.5px Inter;color:var(--mut);padding:11px 15px;white-space:nowrap;border-bottom:2px solid transparent}
.stabs a.on{color:var(--pri);border-bottom-color:var(--pri)}
.ok2{background:#d2f9f4;border:1px solid #9fe9df;color:#0a7d6b;border-radius:12px;
padding:11px 14px;font-size:13.5px;margin-bottom:18px}
.badge{font:600 11px Inter;border-radius:30px;padding:3px 10px}
.b-active{background:#d2f9f4;color:#0a7d6b}.b-tri{background:#fff1cc;color:#946a12}
.b-off{background:var(--line2);color:var(--mut2)}.b-can{background:#ffe4ec;color:#c33153}
.tmpl{border:1px solid var(--line);border-radius:var(--rad);padding:16px 18px;background:var(--card);
margin-bottom:12px;box-shadow:var(--sh)}
.tmpl .cat{font:600 10.5px Inter;letter-spacing:.08em;text-transform:uppercase;color:var(--pri)}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.mini{font:600 12px Inter;padding:8px 14px;border-radius:8px;border:1px solid var(--line);
background:var(--card);color:var(--ink);text-decoration:none;cursor:pointer}
.mini.p{background:var(--pri);border-color:var(--pri);color:#fff}
.mini[disabled]{opacity:.45;cursor:not-allowed}
.tl{position:relative;padding-left:24px}
.tl:before{content:'';position:absolute;left:5px;top:6px;bottom:6px;width:2px;background:var(--line)}
.tl .it{position:relative;margin-bottom:18px}
.tl .it:before{content:'';position:absolute;left:-24px;top:5px;width:11px;height:11px;border-radius:50%;
background:var(--pri);box-shadow:0 0 0 3px var(--bg)}
.tl .d{font:600 11px Inter;letter-spacing:.06em;text-transform:uppercase;color:var(--mut2)}
.brand{font-weight:700;color:var(--ink)}.brand .as{color:var(--pri)}
@media(max-width:900px){
.app{flex-direction:column}
.side{width:auto;height:auto;position:static;border-right:0;border-bottom:1px solid var(--line);
box-shadow:none;padding:14px 16px}
.sidecap{display:none}
.nav{flex-direction:row;flex-wrap:wrap;gap:5px;margin-top:10px}
.nav a{padding:8px 15px}
.main{padding:22px 18px 80px}
}
"""


def _page(title: str, body: str, refresh: bool = False) -> str:
    meta = "<meta http-equiv=refresh content=60>" if refresh else ""
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{title} · Halia</title>"
        "<meta name=viewport content='width=device-width,initial-scale=1'><meta name=robots content=noindex>"
        f"{meta}<link rel=preconnect href=https://fonts.googleapis.com>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' rel=stylesheet>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


_NAV = [
    ("overview", "/console", "Overview"),
    ("revenue", "/console/revenue", "Revenue"),
    ("outreach", "/console/outreach", "Outreach"),
    ("milestones", "/console/milestones", "Milestones"),
    ("content", "/admin", "Content"),
    ("blog", "/admin/blog", "Blog"),
    ("settings", "/console/settings", "Settings"),
]

# The CMS surfaces (Content + Blog) only appear when the editor is enabled.
_ADMIN_NAV = {"content", "blog"}


def _nav_items() -> list[tuple[str, str, str]]:
    """Nav entries for the shell. The CMS surfaces only appear when the editor is enabled."""
    return [(k, h, l) for k, h, l in _NAV if k not in _ADMIN_NAV or config.ADMIN_KEY]


def _status_pill() -> str:
    """A small live status + uptime pill for the shell header."""
    from halia.api.app import system_status
    try:
        st = system_status()
        dot = "ok" if st["status"] == "operational" else "warn"
        label = "All systems operational" if dot == "ok" else "Degraded"
        return (f"<span class=pill><span class='dot {dot}'></span>{label} · up "
                f"{_html.escape(st['uptime_human'])}</span>")
    except Exception:  # pragma: no cover - status must never break a page
        return ""


def _shell(active: str, title: str, body: str, subtitle: str = "", actions: str = "") -> str:
    """Wrap a page body in the app shell: a left sidebar + top header. ``active`` is the nav key.

    ``actions`` is optional header HTML (e.g. a "View site" button) shown left of the status pill.
    The sidebar nav is shared by the Console pages and the CMS, so you move between them in one place.
    """
    nav = "".join(
        f"<a href='{href}' class='{'on' if key == active else ''}'><span class=ic></span>{_html.escape(label)}</a>"
        for key, href, label in _nav_items())
    sub = f"<p class=sub>{subtitle}</p>" if subtitle else ""
    side = (
        "<aside class=side>"
        "<div class=sidelogo><span class=as>&#8258;</span>Halia</div>"
        "<div class=sidecap>Halia · Console</div>"
        f"<nav class=nav>{nav}"
        "<a class=signout href=/console/logout><span class=ic></span>Sign out</a></nav></aside>")
    top = (f"<header class=tophdr><div><h1>{_html.escape(title)}</h1>{sub}</div>"
           f"<div class=topright>{actions}{_status_pill()}</div></header>")
    return _page(title, f"<div class=app>{side}<div class=main><div class=inner>{top}{body}</div></div></div>")


def _login_form(error: str = "", action: str = "/console/login",
                heading: str = "Console dashboard",
                intro: str = "Sign in to see your Halia business at a glance.") -> str:
    """Shared sign-in card. Signing in on either surface opens both (one shared session)."""
    err = f"<p style='color:#c33153;font-size:14px'>{_html.escape(error)}</p>" if error else ""
    return _page("Sign in", (
        "<div class=authwrap><div class=card>"
        "<div class=brand style='font-size:24px;margin-bottom:8px'><span class=as>&#8258;</span> Halia</div>"
        f"<h1 style='font-size:22px;margin:0 0 4px'>{_html.escape(heading)}</h1>"
        f"<p class=sub>{_html.escape(intro)}</p>"
        f"{err}<form method=post action={action} style='margin-top:18px;display:flex;gap:10px;flex-wrap:wrap'>"
        "<input type=password name=key placeholder='Access key' autofocus>"
        "<button class=btn type=submit>Sign in</button></form>"
        "<p class=sub style='margin-top:14px;font-size:12.5px'>One sign-in covers the console and the "
        "content editor.</p></div></div>"))


def _n(v) -> str:
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return "0"


_CCY = {"GBP": "£", "USD": "$", "EUR": "€"}


def _sym(currency: str = "GBP") -> str:
    return _CCY.get((currency or "GBP").upper(), (currency or "").upper() + " ")


def _money(v, currency: str = "GBP") -> str:
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = _sym(currency)
    if abs(v) >= 1000:
        return f"{s}{v / 1000:.1f}k" if abs(v) < 100000 else f"{s}{v / 1000:.0f}k"
    return f"{s}{v:,.0f}"


def _pct(frac: float) -> str:
    return f"{round(frac * 100)}%"


def _today() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def _sparkline(series: list[int]) -> str:
    """A minimal inline-SVG sparkline (same hand-rolled approach as the site's Pareto chart)."""
    vals = [max(0, int(v or 0)) for v in series] or [0]
    w, h, pad = 300, 54, 4
    hi = max(vals) or 1
    n = len(vals)
    step = (w - 2 * pad) / max(1, n - 1)
    pts = [(pad + i * step, h - pad - (v / hi) * (h - 2 * pad)) for i, v in enumerate(vals)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    last_x, last_y = pts[-1]
    return (
        f"<svg class=spark viewBox='0 0 {w} {h}' preserveAspectRatio=none>"
        f"<polyline fill=none stroke='#00a1ff' stroke-width=2 stroke-linejoin=round "
        f"stroke-linecap=round points='{poly}'/>"
        f"<circle cx='{last_x:.1f}' cy='{last_y:.1f}' r=3 fill='#00a1ff'/></svg>"
    )


def _line_chart(series: list[float], labels: list[str] | None = None,
                projected_from: int | None = None) -> str:
    """A labelled line chart (MRR/ARR over time). Points after ``projected_from`` render dashed."""
    vals = [max(0.0, float(v or 0)) for v in series] or [0.0]
    w, h, pl, pr, pt, pb = 520, 190, 44, 12, 14, 26
    hi = max(vals) or 1.0
    n = len(vals)
    iw, ih = w - pl - pr, h - pt - pb
    step = iw / max(1, n - 1)
    xy = [(pl + i * step, pt + ih - (v / hi) * ih) for i, v in enumerate(vals)]
    def _poly(a, b):
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in xy[a:b])
    cut = projected_from if projected_from is not None else n
    solid = f"<polyline fill=none stroke='#00a1ff' stroke-width=2.5 points='{_poly(0, cut)}'/>"
    dash = ""
    if cut < n:
        dash = (f"<polyline fill=none stroke='#00a1ff' stroke-width=2 stroke-dasharray='5 4' "
                f"opacity=.7 points='{_poly(max(0, cut - 1), n)}'/>")
    # y gridlines at 0 / mid / hi
    grid = ""
    for frac in (0, 0.5, 1.0):
        gy = pt + ih - frac * ih
        grid += (f"<line x1={pl} y1={gy:.1f} x2={w - pr} y2={gy:.1f} stroke='#eef2f7'/>"
                 f"<text x=6 y={gy + 3:.1f} font-size=10 fill='#7c8fac'>{_money(hi * frac)}</text>")
    ticks = ""
    if labels:
        for i, lab in enumerate(labels):
            if n > 8 and i % 2:  # thin out crowded axes
                continue
            tx = pl + i * step
            ticks += (f"<text x={tx:.1f} y={h - 6} font-size=9.5 fill='#7c8fac' "
                      f"text-anchor=middle>{_html.escape(lab)}</text>")
    dot = f"<circle cx='{xy[-1][0]:.1f}' cy='{xy[-1][1]:.1f}' r=3.5 fill='#00a1ff'/>"
    return (f"<svg class=chart viewBox='0 0 {w} {h}'>{grid}{solid}{dash}{dot}{ticks}</svg>")


def _donut(segments: list[tuple[str, float]]) -> str:
    """A donut of (label, value) segments with a small legend. Muted brand palette."""
    total = sum(max(0.0, v) for _l, v in segments) or 1.0
    colors = ["#00a1ff", "#8965e5", "#00ceb6", "#ffae1f", "#46caeb", "#ff6692"]
    r, cx, cy, sw = 52, 70, 70, 20
    circ = 2 * 3.14159 * r
    off = 0.0
    arcs, legend = "", ""
    for i, (label, val) in enumerate(segments):
        frac = max(0.0, val) / total
        col = colors[i % len(colors)]
        dash = f"{frac * circ:.2f} {circ:.2f}"
        arcs += (f"<circle cx={cx} cy={cy} r={r} fill=none stroke='{col}' stroke-width={sw} "
                 f"stroke-dasharray='{dash}' stroke-dashoffset='{-off * circ:.2f}' "
                 f"transform='rotate(-90 {cx} {cy})'/>")
        off += frac
        legend += (f"<div class=row style='padding:4px 0'><span><span class=dot style='background:{col}'>"
                   f"</span>{_html.escape(label)}</span><span class=mut>{_pct(frac)}</span></div>")
    svg = (f"<svg viewBox='0 0 140 140' style='width:140px;height:140px;flex:none'>{arcs}</svg>")
    return f"<div style='display:flex;gap:18px;align-items:center;flex-wrap:wrap'>{svg}<div style='flex:1;min-width:150px'>{legend}</div></div>"


def _bars(items: list[tuple[str, float]]) -> str:
    """Horizontal bars (revenue by client). Each item = (label, value)."""
    hi = max((v for _l, v in items), default=0) or 1.0
    rows = ""
    for label, val in items:
        w = max(2.0, (val / hi) * 100)
        rows += (f"<div style='margin:7px 0'><div style='display:flex;justify-content:space-between;"
                 f"font-size:12.5px;margin-bottom:3px'><span>{_html.escape(label)}</span>"
                 f"<span class=mut>{_money(val)}</span></div>"
                 f"<div style='height:8px;background:#eef2f7;border-radius:6px;overflow:hidden'>"
                 f"<div style='height:100%;width:{w:.1f}%;background:linear-gradient(90deg,#46caeb,#00a1ff);"
                 "border-radius:6px'></div></div></div>")
    return rows or "<div class=mut>No revenue yet.</div>"


def _tile(k: str, v: str, d: str = "") -> str:
    dd = f"<div class=d>{d}</div>" if d else ""
    return f"<div class=tile><div class=k>{_html.escape(k)}</div><div class=v>{v}</div>{dd}</div>"


_KIND_LABEL = {"shopify": "Shopify", "woocommerce": "WooCommerce", "bigcommerce": "BigCommerce"}


def _render(d: dict) -> str:
    st = d["status"]
    cl, act, aw = d["clients"], d["activity_week"], d["activity_all"]
    bill = d["billing"]

    kinds = " · ".join(f"{_n(v)} {_KIND_LABEL.get(k, k)}" for k, v in sorted(cl["by_kind"].items())) \
        or "—"

    # A screenshottable headline card for documenting the journey.
    shot = (
        "<div class=shot><div class=mark>&#8258;</div>"
        f"<div class=big>{_n(cl['total'])}</div><div class=cap>clients on Halia</div>"
        "<div class=shotrow>"
        f"<div><div class=n>{_money(bill.get('mrr') or bill.get('mrr_estimate') or 0, bill.get('currency','GBP'))}</div><div class=l>MRR</div></div>"
        f"<div><div class=n>{_n(act['hidden'])}</div><div class=l>hidden VICs this week</div></div>"
        f"<div><div class=n>{_n(aw['scans'])}</div><div class=l>scans all-time</div></div>"
        "</div>"
        f"<div class=stamp>Halia · {_html.escape(d['status']['now'][:10])}</div></div>")

    mrr = ""
    if bill.get("mrr_estimate") is not None:
        mrr = _tile("Est. MRR", f"£{_n(bill['mrr_estimate'])}", "active × plan price (estimate)")
    tiles_clients = "".join([
        _tile("Clients", _n(cl["total"]), kinds),
        _tile("New this week", _n(cl["new_this_week"]), "onboarded"),
        _tile("Active billing", _n(bill["active"]),
              " · ".join(f"{_n(v)} {_html.escape(s)}" for s, v in sorted(bill["breakdown"].items()))
              or "billing off"),
        mrr,
        _tile("Newsletter", _n(d["subscribers"]), "subscribers"),
    ])
    tiles_activity = "".join([
        _tile("Scans", _n(act["scans"]), f"{_n(act['customers'])} customers scanned"),
        _tile("Hidden VICs", _n(act["hidden"]), "surfaced this week"),
        _tile("Emails sent", _n(act["emails"]), f"{_n(aw['emails'])} all-time"),
        _tile("Actions", _n(act["actions"]), "pushes / segments"),
        _tile("POS lookups", _n(act["pos"]), "at the till"),
    ])

    trends = (
        "<div class=two>"
        f"<div class=card><h3>Scans · last 8 weeks</h3>{_sparkline(d['trends']['scans'])}</div>"
        f"<div class=card><h3>Emails · last 8 weeks</h3>{_sparkline(d['trends']['emails'])}</div>"
        "</div>")

    checks = "".join(
        f"<div class=row><span><span class='dot {'ok' if c['status'] == 'operational' else 'warn'}'>"
        f"</span>{_html.escape(c['name'])}</span><span class=mut>{_html.escape(c['note'])}</span></div>"
        for c in st["checks"])
    def _integ_row(name: str, v: dict) -> str:
        recent = f" · +{_n(v['this_week'])} this week" if v["this_week"] else ""
        return (f"<div class=row><span>{_html.escape(name.title())}</span>"
                f"<span class=mut>{_n(v['total'])}{recent}</span></div>")

    integ = "".join(_integ_row(name, v) for name, v in d["integrations"].items())
    health = (
        "<div class=two>"
        f"<div class=card><h3>System health</h3>{checks}"
        f"<div class=row><span class=mut>Host</span><span class=mut>{_html.escape(st['host'])} · "
        f"since {_html.escape(st['started_at'][:10])}</span></div></div>"
        f"<div class=card><h3>Integrations connected</h3>{integ or '<div class=row><span class=mut>None yet</span></div>'}</div>"
        "</div>")

    trows = []
    for r in d["tenants"]:
        integ_badges = "".join(f"<span class=ib>{_html.escape(i)}</span>" for i in r["integrations"]) \
            or "<span class=mut>—</span>"
        good = f"{_n(r['fit'])}/{_n(r['fit'] + r['nofit'])}" if (r["fit"] or r["nofit"]) else "—"
        trows.append(
            "<tr>"
            f"<td><b>{_html.escape(r['label'])}</b><br><span class=mut>{_html.escape(r['shop'])}</span></td>"
            f"<td>{_html.escape(_KIND_LABEL.get(r['kind'], r['kind']))}</td>"
            f"<td>{_html.escape(str(r['billing']))}</td>"
            f"<td>{integ_badges}</td>"
            f"<td class=num>{_n(r['scans'])}</td>"
            f"<td class=num>{_n(r['hidden'])}</td>"
            f"<td class=num>{_n(r['emails'])}</td>"
            f"<td class=num>{_n(r['actions'])}</td>"
            f"<td class=num>{good}</td></tr>")
    table = (
        "<div class=scroll><table><thead><tr>"
        "<th>Client</th><th>Platform</th><th>Billing</th><th>Integrations</th>"
        "<th class=num>Scans</th><th class=num>Hidden</th><th class=num>Emails</th>"
        "<th class=num>Actions</th><th class=num>Good calls</th></tr></thead><tbody>"
        + ("".join(trows) or "<tr><td colspan=9 class=mut>No clients yet.</td></tr>")
        + "</tbody></table></div>"
        "<p class=sub style='margin-top:8px'>Scans/hidden/emails/actions are this week; good calls "
        "are the lifetime associate-feedback tally (per-signal, so an approximate precision cue).</p>")

    body = (
        shot
        + "<div class=sec>Clients &amp; billing</div><div class=grid>" + tiles_clients + "</div>"
        + "<div class=sec>Activity this week</div><div class=grid>" + tiles_activity + "</div>"
        + "<div class=sec>Trends</div>" + trends
        + "<div class=sec>Status</div>" + health
        + "<div class=sec>Clients</div>" + table)
    return _shell("overview", "Overview",
                  body, subtitle=f"Halia at a glance · week {_html.escape(d['week'])}")


_STATUS_BADGE = {"active": "b-active", "trialing": "b-tri", "complete": "b-active",
                 "manual": "b-active", "canceled": "b-can", "past_due": "b-can", "free": "b-off"}


def _badge(status: str) -> str:
    cls = _STATUS_BADGE.get(str(status), "b-off")
    return f"<span class='badge {cls}'>{_html.escape(str(status))}</span>"


def _render_revenue(d: dict) -> str:
    ccy = d["currency"]
    hero = (
        "<div class=shot><div class=mark>&#8258;</div>"
        f"<div class=big>{_money(d['mrr'], ccy)}</div><div class=cap>monthly recurring revenue</div>"
        "<div class=shotrow>"
        f"<div><div class=n>{_money(d['arr'], ccy)}</div><div class=l>ARR (run-rate)</div></div>"
        f"<div><div class=n>{_n(d['paying'])}</div><div class=l>paying clients</div></div>"
        f"<div><div class=n>{_money(d['incoming_30d'], ccy)}</div><div class=l>due in 30 days</div></div>"
        "</div>"
        f"<div class=stamp>Halia revenue · {_html.escape(_today())}</div></div>")

    notice = ""
    if not d["enabled"]:
        notice = ("<div class=ok2 style='background:#fdf3e0;border-color:#e8cfa0;color:#8a5a12'>"
                  "Stripe billing is not configured, so figures come from your manual entries in "
                  "Settings → Revenue. Turn on Stripe to pull live subscriptions.</div>")

    nxt = d["next_payment"]
    tiles = "".join([
        _tile("MRR", _money(d["mrr"], ccy), "recurring / month"),
        _tile("ARR", _money(d["arr"], ccy), "MRR × 12"),
        _tile("Paying clients", _n(d["paying"]), f"of {_n(len(d['clients']))}"),
        _tile("Next payment", _money(nxt["amount"], nxt["currency"]) if nxt else "—",
              (f"{_html.escape(nxt['label'])} · {_html.escape(nxt['renewal'])}") if nxt else "no renewals on file"),
    ])

    proj = (f"<div class=card><h3>Expected MRR · next 12 months</h3>"
            f"{_line_chart(d['trend'], d['trend_labels'], projected_from=1)}"
            "<p class=sub style='margin-top:6px'>Current subscriptions carried forward; scheduled "
            "cancellations drop off at their renewal. Not banked revenue.</p></div>")
    mixcard = (f"<div class=card><h3>Revenue mix</h3>"
               f"{_donut([(k, v) for k, v in d['mix']]) if d['mix'] else '<div class=mut>No paying clients yet.</div>'}</div>")

    bars = _bars([(c["label"], c["monthly"]) for c in
                  sorted(d["clients"], key=lambda c: -c["monthly"]) if c["monthly"] > 0][:12])
    barcard = f"<div class=card><h3>MRR by client</h3>{bars}</div>"

    cal_rows = "".join(
        f"<tr><td><b>{_html.escape(c['label'])}</b></td><td>{_html.escape(c['renewal'])}</td>"
        f"<td>{_badge(c['status'])}{' · cancels' if c['cancel'] else ''}</td>"
        f"<td class=num>{_money(c['amount'], c['currency'])}</td>"
        f"<td class=mut>{c['source']}</td></tr>"
        for c in d["renewals"])
    cal = (
        "<div class=scroll><table><thead><tr><th>Client</th><th>Renews</th><th>Status</th>"
        "<th class=num>Amount</th><th>Source</th></tr></thead><tbody>"
        + (cal_rows or "<tr><td colspan=5 class=mut>No renewal dates yet.</td></tr>")
        + "</tbody></table></div>")

    body = (
        hero + notice
        + "<div class=sec>Headline</div><div class=grid>" + tiles + "</div>"
        + "<div class=sec>Projection &amp; mix</div><div class=two>" + proj + mixcard + "</div>"
        + "<div class=sec>By client</div>" + barcard
        + "<div class=sec>Renewals &amp; incoming payments</div>" + cal)
    return _shell("revenue", "Revenue", body, subtitle="MRR, ARR, renewals and what's coming in")


# ── outreach (template emails to clients) ────────────────────────────────────────
def _fill(text: str, ctx: dict) -> str:
    out = str(text or "")
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v or ""))
    return out


def _client_ctx(client: dict) -> dict:
    from halia.console_config import console_settings
    name = client["label"].split()[0] if client.get("label") else "there"
    return {"client_name": name, "store": client.get("label") or client["shop"],
            "sender": console_settings().get("sender_name") or "the Halia team"}


def _render_outreach(templates: list[dict], clients: list[dict], can_send: bool) -> str:
    import urllib.parse as _up

    tpl_cards = ""
    for t in templates:
        tpl_cards += (
            f"<div class=tmpl><div class=cat>{_html.escape(t.get('category', ''))}</div>"
            f"<b>{_html.escape(t.get('name', ''))}</b>"
            f"<div class=mut style='font-size:12.5px;margin-top:2px'>{_html.escape(t.get('subject', ''))}</div></div>")

    rows = ""
    for c in clients:
        ctx = _client_ctx(c)
        email = c.get("email") or ""
        picks = ""
        for t in templates:
            subj = _fill(t.get("subject", ""), ctx)
            body = _fill(t.get("body", ""), ctx)
            mailto = (f"mailto:{_up.quote(email)}?subject={_up.quote(subj)}&body={_up.quote(body)}"
                      if email else "")
            ml = (f"<a class=mini href=\"{mailto}\">{_html.escape(t['name'])}</a>" if mailto
                  else f"<span class='mini' style='opacity:.5'>{_html.escape(t['name'])} (no email)</span>")
            send = ""
            if email and can_send:
                send = (f"<button class='mini p' onclick=\"consoleSend('{_html.escape(c['shop'])}',"
                        f"'{_html.escape(t['id'])}',this)\">Send</button>")
            picks += f"<span style='display:inline-flex;gap:4px;margin:0 8px 6px 0'>{ml}{send}</span>"
        rows += (
            f"<tr><td><b>{_html.escape(c['label'])}</b><br>"
            f"<span class=mut>{_html.escape(email or 'no email on file')}</span></td>"
            f"<td>{_badge(c['billing'])}</td><td>{picks}</td></tr>")

    tip = "" if can_send else ("<div class=ok2 style='background:#fdf3e0;border-color:#e8cfa0;color:#8a5a12'>"
                               "One-click send needs email configured (HALIA_BREVO_API_KEY). The "
                               "mailto links still work and open your own inbox.</div>")
    js = ("<script>function consoleSend(shop,tpl,btn){btn.disabled=true;btn.textContent='Sending…';"
          "fetch('/console/outreach/send',{method:'POST',headers:{'content-type':'application/json'},"
          "body:JSON.stringify({shop:shop,template_id:tpl})}).then(r=>r.json()).then(d=>{"
          "btn.textContent=d.ok?'Sent ✓':'Failed';}).catch(()=>{btn.textContent='Failed';});}</script>")
    table = (
        "<div class=scroll><table><thead><tr><th>Client</th><th>Billing</th>"
        "<th>Send a template</th></tr></thead><tbody>"
        + (rows or "<tr><td colspan=3 class=mut>No clients yet.</td></tr>")
        + "</tbody></table></div>")
    body = (
        tip
        + "<div class=sec>Templates</div><div class=grid style='grid-template-columns:repeat(auto-fill,minmax(230px,1fr))'>"
        + tpl_cards + "</div>"
        + "<div class=sec>Your clients</div>" + table + js
        + "<p class=sub style='margin-top:8px'>Edit these templates in Settings → Outreach. "
        "Placeholders {client_name}, {store} and {sender} fill in automatically.</p>")
    return _shell("outreach", "Outreach", body, subtitle="Send a warm, on-brand note to any client")


def _render_milestones(milestones: list[dict], snapshot: dict) -> str:
    ccy = snapshot.get("currency", "GBP")
    snap = (
        "<div class=shot><div class=mark>&#8258;</div>"
        f"<div class=cap style='margin-bottom:8px'>Where Halia stands today</div>"
        "<div class=shotrow>"
        f"<div><div class=n>{_n(snapshot.get('clients', 0))}</div><div class=l>clients</div></div>"
        f"<div><div class=n>{_money(snapshot.get('mrr', 0), ccy)}</div><div class=l>MRR</div></div>"
        f"<div><div class=n>{_money(snapshot.get('arr', 0), ccy)}</div><div class=l>ARR</div></div>"
        f"<div><div class=n>{_n(snapshot.get('scans_all', 0))}</div><div class=l>scans all-time</div></div>"
        "</div>"
        f"<div class=stamp>Halia · {_html.escape(snapshot.get('date', ''))}</div></div>")

    items = ""
    for m in sorted(milestones, key=lambda x: x.get("date", ""), reverse=True):
        items += (f"<div class=it><div class=d>{_html.escape(m.get('date', ''))}</div>"
                  f"<div style='font:600 17px Inter;color:#111c2d;margin:2px 0'>{_html.escape(m.get('title', ''))}</div>"
                  f"<div class=mut style='font-size:13.5px'>{_html.escape(m.get('note', ''))}</div></div>")
    timeline = f"<div class=tl>{items or '<div class=mut>No milestones yet. Add your first in Settings → Milestones.</div>'}</div>"

    body = (snap + "<div class=sec>Journey</div>" + timeline
            + "<p class=sub style='margin-top:10px'>The snapshot card and each milestone are made to "
            "screenshot. Add milestones in Settings → Milestones.</p>")
    return _shell("milestones", "Milestones", body, subtitle="Document the journey as Halia grows")


# ── settings (tabbed, POST forms) ────────────────────────────────────────────────
_STABS = [("defaults", "New-client defaults"), ("access", "Access & comps"),
          ("revenue", "Revenue"), ("outreach", "Outreach"), ("milestones", "Milestones")]


def _field(label: str, name: str, value: str = "", kind: str = "text", hint: str = "",
           placeholder: str = "") -> str:
    val = _html.escape(str(value if value is not None else ""))
    ph = f"placeholder='{_html.escape(placeholder)}'" if placeholder else ""
    inp = f"<input name='{name}' type='{kind}' value='{val}' {ph}>"
    hh = f"<div class=hint>{_html.escape(hint)}</div>" if hint else ""
    return f"<div class=f><label>{_html.escape(label)}</label>{inp}{hh}</div>"


def _render_settings(tab: str, saved: bool = False) -> str:
    from halia.console_config import console_settings
    st = console_settings()
    tab = tab if tab in {k for k, _l in _STABS} else "defaults"
    tabs = "".join(f"<a href='/console/settings?tab={k}' class='{'on' if k == tab else ''}'>{_html.escape(l)}</a>"
                   for k, l in _STABS)
    ok = "<div class=ok2>Saved.</div>" if saved else ""

    def form(inner: str) -> str:
        return (f"<form method=post action=/console/settings><input type=hidden name=tab value='{tab}'>"
                f"{inner}<div style='margin-top:12px'><button class=btn type=submit>Save changes</button></div></form>")

    if tab == "defaults":
        grades = ",".join(st.get("default_notify_grades") or [])
        inner = (
            _field("Default VIC spend threshold (£)", "default_vic_threshold",
                   st.get("default_vic_threshold", 5000), "number",
                   "Applied to newly onboarded clients. Each client can still override it.")
            + _field("Default alert grades", "default_notify_grades", grades, "text",
                     "Comma-separated, e.g. A*,A")
            + _field("Your name / sign-off", "sender_name", st.get("sender_name", ""), "text",
                     "Fills the {sender} placeholder in client emails.")
            + _field("Plan currency", "plan_currency", st.get("plan_currency", "GBP"), "text",
                     "GBP, USD or EUR")
            + _field("Plan price / month (optional)", "plan_price", st.get("plan_price") or "", "number",
                     "Overrides the Stripe price for MRR display. Leave blank to use Stripe."))
        body = form(inner)
    elif tab == "access":
        free = "\n".join(st.get("free_shops") or []) if isinstance(st.get("free_shops"), list) else ""
        inner = (
            _field("Self-serve signup code", "signup_code", st.get("signup_code") or "", "text",
                   "Required on the /connect page. Blank = open onboarding.")
            + "<div class=f><label>Comped clients (one shop per line)</label>"
            f"<textarea name=free_shops placeholder='acme.myshopify.com'>{_html.escape(free)}</textarea>"
            "<div class=hint>These clients bypass billing and see the full dashboard.</div></div>")
        body = form(inner)
    elif tab == "revenue":
        overrides = st.get("revenue_overrides") or {}
        rows = ""
        for c in _iter_clients():
            o = overrides.get(c["shop"], {})
            rows += (
                f"<tr><td><b>{_html.escape(c['label'])}</b><br><span class=mut>{_html.escape(c['shop'])}</span></td>"
                f"<td><input name='rev_{_html.escape(c['shop'])}_amount' type=number step=0.01 "
                f"value='{_html.escape(str(o.get('amount', '')))}' style='width:110px'></td>"
                f"<td><input name='rev_{_html.escape(c['shop'])}_renewal' type=date "
                f"value='{_html.escape(str(o.get('renewal_date', '')))}'></td>"
                f"<td><input name='rev_{_html.escape(c['shop'])}_status' type=text placeholder=manual "
                f"value='{_html.escape(str(o.get('status', '')))}' style='width:110px'></td></tr>")
        table = ("<p class=sub>Manual figures for clients not on Stripe (comped, invoiced, early). "
                 "Stripe subscriptions override these automatically.</p>"
                 "<div class=scroll><table><thead><tr><th>Client</th><th>MRR amount</th>"
                 "<th>Renews on</th><th>Status</th></tr></thead><tbody>"
                 + (rows or "<tr><td colspan=4 class=mut>No clients yet.</td></tr>")
                 + "</tbody></table></div>")
        body = form(table)
    elif tab == "outreach":
        tpls = st.get("client_templates") or []
        blocks = ""
        for t in tpls:
            tid = _html.escape(t.get("id", ""))
            blocks += (
                f"<div class=tmpl><div class=cat>{_html.escape(t.get('category', ''))} · {_html.escape(t.get('name', ''))}</div>"
                + _field("Subject", f"tpl_{tid}_subject", t.get("subject", ""))
                + f"<div class=f><label>Body</label><textarea name='tpl_{tid}_body'>{_html.escape(t.get('body', ''))}</textarea></div>"
                + "</div>")
        body = form(blocks + "<p class=sub>Placeholders {client_name}, {store}, {sender} fill in when sent.</p>")
    else:  # milestones
        ms = sorted(st.get("milestones") or [], key=lambda x: x.get("date", ""), reverse=True)
        existing = ""
        for i, m in enumerate(ms):
            existing += (
                f"<div class=tmpl><input type=hidden name='ms_{i}_keep' value='1'>"
                + _field("Date", f"ms_{i}_date", m.get("date", ""), "date")
                + _field("Title", f"ms_{i}_title", m.get("title", ""))
                + f"<div class=f><label>Note</label><textarea name='ms_{i}_note'>{_html.escape(m.get('note', ''))}</textarea></div>"
                + f"<label style='font-size:12.5px;color:#a3392a'><input type=checkbox name='ms_{i}_delete' value='1'> Remove this milestone</label>"
                + "</div>")
        add = ("<div class=tmpl><div class=cat>Add a milestone</div>"
               + _field("Date", "ms_new_date", _today(), "date")
               + _field("Title", "ms_new_title", "", "text", placeholder="First paying client")
               + "<div class=f><label>Note</label><textarea name=ms_new_note placeholder='What happened'></textarea></div></div>")
        body = form(existing + add)

    return _shell("settings", "Settings",
                  ok + f"<div class=stabs>{tabs}</div>" + body,
                  subtitle="Change things yourself, without asking a developer")


def _apply_settings(tab: str, form: dict) -> None:
    """Persist one settings tab from posted form data into the _console blob."""
    from halia.api.settings import _clean_templates
    from halia.console_config import console_settings, save_console_settings

    def g(k, default=""):
        v = form.get(k, default)
        return v if v is not None else default

    if tab == "defaults":
        patch = {"sender_name": str(g("sender_name")).strip(),
                 "plan_currency": (str(g("plan_currency")).strip() or "GBP").upper()}
        try:
            patch["default_vic_threshold"] = float(g("default_vic_threshold") or 5000)
        except (TypeError, ValueError):
            patch["default_vic_threshold"] = 5000
        grades = [x.strip() for x in str(g("default_notify_grades")).split(",") if x.strip()]
        patch["default_notify_grades"] = grades or ["A*", "A"]
        price = str(g("plan_price")).strip()
        patch["plan_price"] = float(price) if price else None
        save_console_settings(patch)
    elif tab == "access":
        code = str(g("signup_code")).strip()
        shops = [x.strip() for x in re.split(r"[\s,]+", str(g("free_shops"))) if x.strip()]
        save_console_settings({"signup_code": code or None, "free_shops": shops})
    elif tab == "revenue":
        overrides = {}
        for key in form:
            if key.startswith("rev_") and key.endswith("_amount"):
                shop = key[4:-7]
                amount = str(form.get(f"rev_{shop}_amount") or "").strip()
                renewal = str(form.get(f"rev_{shop}_renewal") or "").strip()
                status = str(form.get(f"rev_{shop}_status") or "").strip()
                if amount or renewal or status:
                    overrides[shop] = {"amount": float(amount) if amount else 0.0,
                                       "renewal_date": renewal or None,
                                       "status": status or "manual"}
        save_console_settings({"revenue_overrides": overrides})
        _REV_CACHE.clear()
    elif tab == "outreach":
        tpls = []
        for t in console_settings().get("client_templates") or []:
            tid = t.get("id", "")
            subj = form.get(f"tpl_{tid}_subject")
            bodyv = form.get(f"tpl_{tid}_body")
            tpls.append({**t,
                         "subject": (subj if subj is not None else t.get("subject", "")),
                         "body": (bodyv if bodyv is not None else t.get("body", ""))})
        # Reuse the merchant template validator (caps lengths), then restore id/category.
        cleaned = _clean_templates([{"name": t["name"], "subject": t["subject"], "body": t["body"]}
                                    for t in tpls])
        for base, cl in zip(tpls, cleaned):
            base["subject"], base["body"] = cl["subject"], cl["body"]
        save_console_settings({"client_templates": tpls})
    elif tab == "milestones":
        out = []
        i = 0
        while f"ms_{i}_keep" in form or f"ms_{i}_date" in form:
            if not form.get(f"ms_{i}_delete"):
                title = str(form.get(f"ms_{i}_title") or "").strip()
                if title:
                    out.append({"date": str(form.get(f"ms_{i}_date") or "").strip(),
                                "title": title, "note": str(form.get(f"ms_{i}_note") or "").strip()})
            i += 1
        new_title = str(form.get("ms_new_title") or "").strip()
        if new_title:
            out.append({"date": str(form.get("ms_new_date") or _today()).strip(),
                        "title": new_title, "note": str(form.get("ms_new_note") or "").strip()})
        save_console_settings({"milestones": out})


# ── routes ───────────────────────────────────────────────────────────────────────
def register(app) -> None:

    @app.get("/console", response_class=HTMLResponse)
    def console_home(request: Request):
        if not config.CONSOLE_KEY:
            return HTMLResponse(_page("Console disabled",
                "<div class=authwrap><div class=card><h1 style='font-size:22px;margin:0 0 6px'>"
                "Console dashboard</h1><p class=sub>Set <code>HALIA_CONSOLE_KEY</code> in the "
                "environment to enable it.</p></div></div>"))
        if not _console_ok(request):
            return HTMLResponse(_login_form())
        return HTMLResponse(_render(_dashboard_data()))

    @app.post("/console/login", response_class=HTMLResponse)
    def console_login(request: Request, key: str = Form("")):
        if not config.CONSOLE_KEY or not hmac.compare_digest(key.strip(), config.CONSOLE_KEY):
            return HTMLResponse(_login_form("That key is not right."), status_code=401)
        resp = RedirectResponse("/console", status_code=303)
        resp.set_cookie(_CONSOLE_COOKIE, _make_cookie(), httponly=True,
                        secure=(config.HALIA_APP_URL or "").startswith("https"),
                        samesite="lax", max_age=60 * 60 * 12)
        staff_auth.set_session(resp)          # also open the CMS (one sign-in for both)
        return resp

    @app.get("/console/logout")
    def console_logout():
        resp = RedirectResponse("/console", status_code=303)
        resp.delete_cookie(_CONSOLE_COOKIE)
        staff_auth.clear_session(resp)        # signing out here signs out of the CMS too
        return resp

    @app.get("/console/data.json", include_in_schema=False)
    def console_data(request: Request):
        if not _console_ok(request):
            raise HTTPException(403, "Not signed in.")
        return JSONResponse(_dashboard_data())

    def _gate(request: Request):
        """Return an HTMLResponse to short-circuit with (login/disabled), or None if signed in."""
        if not config.CONSOLE_KEY:
            return HTMLResponse(_page("Console disabled",
                "<div class=authwrap><div class=card><h1 style='font-size:22px;margin:0 0 6px'>"
                "Console dashboard</h1><p class=sub>Set <code>HALIA_CONSOLE_KEY</code> to enable it.</p>"
                "</div></div>"))
        if not _console_ok(request):
            return HTMLResponse(_login_form())
        return None

    @app.get("/console/revenue", response_class=HTMLResponse)
    def console_revenue(request: Request):
        return _gate(request) or HTMLResponse(_render_revenue(_revenue_data()))

    @app.get("/console/outreach", response_class=HTMLResponse)
    def console_outreach(request: Request):
        gate = _gate(request)
        if gate:
            return gate
        import halia.notify as notify
        from halia.console_config import console_settings
        return HTMLResponse(_render_outreach(
            console_settings().get("client_templates") or [], _iter_clients(),
            can_send=notify.email_configured()))

    @app.post("/console/outreach/send")
    def console_outreach_send(request: Request, payload=Body(...)):
        if not _console_ok(request):
            raise HTTPException(403, "Not signed in.")
        import halia.notify as notify
        from halia.console_config import console_settings

        shop = str((payload or {}).get("shop") or "")
        tpl_id = str((payload or {}).get("template_id") or "")
        client = next((c for c in _iter_clients() if c["shop"] == shop), None)
        if not client or not client.get("email"):
            raise HTTPException(404, "No email on file for that client.")
        tpl = next((t for t in (console_settings().get("client_templates") or [])
                    if t.get("id") == tpl_id), None)
        if not tpl:
            raise HTTPException(404, "Unknown template.")
        ctx = _client_ctx(client)
        subject = _fill(tpl.get("subject", ""), ctx)
        body_txt = _fill(tpl.get("body", ""), ctx)
        html_body = "<div style='font:15px/1.6 -apple-system,Segoe UI,sans-serif;color:#1c1b18'>" \
            + _html.escape(body_txt).replace("\n", "<br>") + "</div>"
        ok = notify.send_email(client["email"], subject, html_body, text=body_txt, shop=shop)
        return JSONResponse({"ok": bool(ok)})

    @app.get("/console/milestones", response_class=HTMLResponse)
    def console_milestones(request: Request):
        gate = _gate(request)
        if gate:
            return gate
        d = _dashboard_data()
        rev = _revenue_data()
        snapshot = {"clients": d["clients"]["total"], "mrr": rev["mrr"], "arr": rev["arr"],
                    "currency": rev["currency"], "scans_all": d["activity_all"]["scans"],
                    "date": _today()}
        from halia.console_config import console_settings
        return HTMLResponse(_render_milestones(console_settings().get("milestones") or [], snapshot))

    @app.get("/console/settings", response_class=HTMLResponse)
    def console_settings_page(request: Request, tab: str = "defaults", saved: int = 0):
        return _gate(request) or HTMLResponse(_render_settings(tab, saved=bool(saved)))

    @app.post("/console/settings")
    async def console_settings_save(request: Request):
        if not _console_ok(request):
            raise HTTPException(403, "Not signed in.")
        form = dict(await request.form())
        tab = str(form.get("tab") or "defaults")
        _apply_settings(tab, form)
        return RedirectResponse(f"/console/settings?tab={tab}&saved=1", status_code=303)

