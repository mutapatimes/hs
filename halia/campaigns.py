"""Campaign monitoring metrics — pure functions over the in-RAM book (zero-retention).

A campaign is a saved monitoring window: a name, a date range, and a target (tiers /
signals plus optional hand-picked member ids). Nothing about customers is stored beyond
opaque ids; the sales metrics here are computed live from the dashboard payload's client
rows (each carries its grade, its fired signals, and its order history), so we keep nothing.

Everything is a plain function returning plain dicts: easy to test, easy to render.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

_DAY = "%Y-%m-%d"
QUIET_DAYS = 90   # no order for this long before the window = "gone quiet"; a buy in-window = reactivated


def _d(value) -> date | None:
    if isinstance(value, date):
        return value
    s = str(value or "")[:10]
    try:
        return datetime.strptime(s, _DAY).date()
    except ValueError:
        return None


def select_members(campaign: dict, clients: list[dict]) -> list[dict]:
    """Clients targeted by the campaign: hand-picked ids, OR a matching grade/tier, OR any
    of the targeted signals (union). An empty target selects nobody."""
    cfg = campaign.get("config") or {}
    tiers = {str(t).upper() for t in cfg.get("tiers", [])}
    signals = set(cfg.get("signals", []))
    members = {str(m) for m in cfg.get("members", [])}
    out = []
    for c in clients:
        cid = str(c.get("cid", ""))
        csigs = {s.get("seg") for s in c.get("signals", [])} if c.get("signals") else set(c.get("segs", []))
        if (cid and cid in members) or (str(c.get("tier", "")).upper() in tiers and tiers) \
                or (signals and (signals & csigs)):
            out.append(c)
    return out


def _week_buckets(start: date, end: date) -> list[str]:
    """7-day bucket start-dates spanning [start, end] inclusive."""
    out, cur = [], start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=7)
    return out


def _bucket_of(d: date, start: date) -> str:
    return (start + timedelta(days=((d - start).days // 7) * 7)).isoformat()


def campaign_metrics(campaign: dict, clients: list[dict]) -> dict:
    """Compute KPIs + time series + per-signal / per-grade breakdowns for a campaign.

    ``campaign`` = {"name","starts","ends","config":{tiers,signals,members}}.
    ``clients`` = payload rows, each {"cid","name","tier","spent","signals":[{"seg":..}],
    "orders":[{"date","amount"}]}.
    """
    start, end = _d(campaign.get("starts")), _d(campaign.get("ends"))
    members = select_members(campaign, clients)
    buckets = _week_buckets(start, end) if start and end and start <= end else []
    series = {b: 0.0 for b in buckets}
    by_signal: dict[str, float] = {}
    by_tier: dict[str, float] = {}
    seg_label = {}
    total_rev = total_orders = buyers = 0.0
    reactivated = 0
    reactivated_rev = 0.0
    rows = []

    for c in members:
        rev = 0.0
        ordn = 0
        last_pre = None   # most recent order BEFORE the window (to spot "gone quiet")
        for o in c.get("orders", []) or []:
            od = _d(o.get("date"))
            if od is None or start is None or end is None:
                continue
            if od < start:
                if last_pre is None or od > last_pre:
                    last_pre = od
                continue
            if not (start <= od <= end):
                continue
            amt = float(o.get("amount") or 0)
            rev += amt
            ordn += 1
            b = _bucket_of(od, start)
            if b in series:
                series[b] += amt
        total_rev += rev
        total_orders += ordn
        if rev > 0:
            buyers += 1
            # reactivation: they had gone quiet before the window (a prior order, long ago) and
            # bought during it. Their in-window spend is the win-back the campaign recovered.
            if last_pre is not None and (start - last_pre).days >= QUIET_DAYS:
                reactivated += 1
                reactivated_rev += rev
        tier = str(c.get("tier") or "—")
        by_tier[tier] = by_tier.get(tier, 0.0) + rev
        for s in c.get("signals", []) or []:
            seg = s.get("seg")
            if not seg:
                continue
            by_signal[seg] = by_signal.get(seg, 0.0) + rev
            seg_label.setdefault(seg, (s.get("d", "").split(":")[0] or seg))
        rows.append({"cid": str(c.get("cid", "")), "name": c.get("name", "Customer"),
                     "tier": tier, "revenue": round(rev, 2), "orders": ordn})

    # Campaign-link attribution: in-window orders whose UTM matches this campaign's tag, across the
    # whole book (a tagged link can be clicked by anyone, not only targeted members). Populated only
    # when order UTM data is present (config.SHOPIFY_JOURNEY on); otherwise these stay zero.
    camp_utm = ((campaign.get("config") or {}).get("utm") or {}).get("campaign") or ""
    att_rev = 0.0
    att_orders = 0
    att_buyers = set()
    if camp_utm and start and end:
        for c in clients:
            bought = False
            for o in c.get("orders", []) or []:
                if (o.get("utm") or "") != camp_utm:
                    continue
                od = _d(o.get("date"))
                if od is None or not (start <= od <= end):
                    continue
                att_rev += float(o.get("amount") or 0)
                att_orders += 1
                bought = True
            if bought:
                att_buyers.add(str(c.get("cid", "")))

    n = len(members)
    kpis = {
        "members": n,
        "buyers": int(buyers),
        "conversion": round(buyers / n, 3) if n else 0.0,
        "revenue": round(total_rev, 2),
        "orders": int(total_orders),
        "aov": round(total_rev / total_orders, 2) if total_orders else 0.0,
        "reactivated": reactivated,
        "reactivated_revenue": round(reactivated_rev, 2),
        "attributed_revenue": round(att_rev, 2),
        "attributed_orders": att_orders,
        "attributed_buyers": len(att_buyers),
    }
    return {
        "name": campaign.get("name", "Campaign"),
        "starts": campaign.get("starts"), "ends": campaign.get("ends"),
        "kpis": kpis,
        "series": [{"week": b, "value": round(series[b], 2)} for b in buckets],
        "by_signal": sorted(({"seg": k, "label": seg_label.get(k, k), "value": round(v, 2)}
                             for k, v in by_signal.items()), key=lambda r: -r["value"]),
        "by_tier": sorted(({"tier": k, "value": round(v, 2)} for k, v in by_tier.items()),
                          key=lambda r: -r["value"]),
        "top": sorted(rows, key=lambda r: -r["revenue"])[:10],
    }
