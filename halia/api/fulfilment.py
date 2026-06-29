"""Fulfilment view — the read-only pick list, priority-first.

The insight that triggered the multi-surface rearchitecture: the fulfilment team
touches the physical moment (the parcel, the packing, the dispatch) but is flying
blind on who's who. Give them the Halia grade and a high-value client's order can get
the better box, the handwritten note, priority dispatch — clienteling expressed through
logistics.

This is a thin surface: it only reads today's orders from the in-memory cache, joins each
to its customer's score, and renders them with A*/A floated to the top of the queue,
each with the discreet associate gesture. No new scoring — it rides the same brain.
"""
from __future__ import annotations

import html

from fastapi.responses import HTMLResponse

_TIER_COLOR = {"A*": "#9A7B33", "A": "#3B6E47", "B": "#5A6B86", "C": "#9A958A"}

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Halia · Fulfilment pick list</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 :root{{--ink:#1c1b18;--soft:#6b675e;--line:#e7e3d9;--bg:#faf8f3}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
   font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
 header{{padding:22px 28px;border-bottom:1px solid var(--line);background:#fff}}
 h1{{margin:0;font-size:19px;letter-spacing:.2px}} .sub{{color:var(--soft);font-size:13px;margin-top:3px}}
 .wrap{{max-width:980px;margin:0 auto;padding:22px 28px}}
 .row{{display:flex;align-items:center;gap:16px;padding:14px 16px;background:#fff;
   border:1px solid var(--line);border-radius:12px;margin-bottom:10px}}
 .row.prio{{border-color:#d8c79a;box-shadow:0 1px 0 #efe7d2}}
 .badge{{flex:none;width:42px;height:42px;border-radius:50%;display:flex;align-items:center;
   justify-content:center;color:#fff;font-weight:700;font-size:15px}}
 .who{{flex:1;min-width:0}} .who b{{font-weight:650}} .ord{{color:var(--soft);font-size:12.5px}}
 .gesture{{flex:1.4;color:var(--soft);font-size:13px}}
 .score{{flex:none;text-align:right;font-variant-numeric:tabular-nums}}
 .score b{{font-size:17px}} .score span{{display:block;color:var(--soft);font-size:11.5px}}
 .none{{color:#a8a399}}
 .empty{{padding:60px;text-align:center;color:var(--soft)}}
</style></head><body>
<header><h1>Fulfilment pick list</h1>
<div class="sub">Today's orders, highest-value clients first — pack with care, add the touch.</div></header>
<div class="wrap">{rows}</div></body></html>"""


def _row_html(order: dict) -> str:
    r = order["result"]
    oid = html.escape(str(order["order_id"]))
    when = html.escape(str(order.get("created_at") or "")[:10])
    if r is None or not r.flagged:
        return (f'<div class="row"><div class="badge" style="background:#cfcabd">—</div>'
                f'<div class="who"><b class="none">Unscored customer</b>'
                f'<div class="ord">Order {oid} · {when}</div></div>'
                f'<div class="gesture none">No signal on file — standard handling.</div>'
                f'<div class="score none"><b>—</b></div></div>')
    color = _TIER_COLOR.get(r.grade, "#9A958A")
    prio = " prio" if r.is_priority else ""
    name = html.escape(r.email or r.customer_id or "Client")
    gesture = html.escape(r.gesture or "")
    reasons = html.escape(r.reasons or "")
    return (f'<div class="row{prio}"><div class="badge" style="background:{color}">{html.escape(r.grade)}</div>'
            f'<div class="who"><b>{name}</b><div class="ord">Order {oid} · {when} · {reasons}</div></div>'
            f'<div class="gesture">{gesture}</div>'
            f'<div class="score"><b>{r.score}</b><span>spend £{int(r.spend):,}</span></div></div>')


def register(app) -> None:
    """Attach GET /fulfilment to the FastAPI app, reading from the RAM cache."""
    from fastapi import Depends

    from halia.api import data
    from halia.api.shopify_auth import require_shop

    @app.get("/fulfilment", response_class=HTMLResponse)
    def fulfilment_view(shop: str = Depends(require_shop), limit: int = 100):
        entry = data.results_for(shop)
        orders = data.recent_orders(entry, limit) if entry else []
        if not orders:
            body = '<div class="empty">No orders yet. Run <code>python -m halia.sync</code> to populate.</div>'
        else:
            body = "".join(_row_html(o) for o in orders)
        return HTMLResponse(_PAGE.format(rows=body))
