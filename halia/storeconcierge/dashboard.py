"""Render the Store Concierge clienteling desk from a clienteling payload.

Deliberately small and server-rendered: a stat row, a customer table, and the win-back
list, in the Store Concierge look (white, squared, Helvetica, plum). No scores, no grades,
no wealth language. This is the "simple quick-wins" surface, not a CRM.
"""
from __future__ import annotations

import html as _html


def _money(v: float) -> str:
    try:
        return "£" + f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "£0"


def _rows(customers: list, *, winback: bool = False) -> str:
    out = []
    for c in customers:
        name = _html.escape(c.get("name", "") or "Customer")
        email = _html.escape(c.get("email", "") or "")
        cid = _html.escape(str(c.get("cid", "")))
        status = "lapsed" if c.get("status") == "lapsed" else "active"
        last = _html.escape(c.get("last", "") or "—")
        days = int(c.get("days", 0))
        ago = "today" if days <= 0 else (f"{days} days ago" if days < 400 else "over a year ago")
        # the one action: write to this customer, from the merchant's own mail client
        subj = "A little something we saved for you" if winback else "A note from us"
        mailto = (f"mailto:{email}?subject={_html.escape(subj)}"
                  if email else "#")
        out.append(
            f'<tr data-name="{name.lower()}" data-email="{email.lower()}">'
            f'<td class="nm">{name}<span class="em">{email or "no email on file"}</span></td>'
            f'<td class="num">{int(c.get("orders", 0))}</td>'
            f'<td class="num">{_money(c.get("spent", 0))}</td>'
            f'<td>{last}<span class="ago">{ago}</span></td>'
            f'<td><span class="pill {status}">{status}</span></td>'
            f'<td class="act"><a href="{mailto}">Write &rsaquo;</a></td>'
            f'</tr>'
        )
    return "".join(out) or '<tr><td colspan="6" class="empty">No customers here yet.</td></tr>'


def render_clienteling(payload: dict, *, demo: bool = False) -> str:
    s = payload.get("stats", {})
    banner = (
        '<div class="demo">Sample data from a fictional shop. This is what your desk looks like.</div>'
        if demo else ""
    )
    stat = lambda n, l: f'<div class="stat"><div class="n">{n}</div><div class="l">{l}</div></div>'
    stats = "".join([
        stat(f'{s.get("customers", 0):,}', "customers"),
        stat(f'{s.get("active", 0):,}', "active"),
        stat(f'{s.get("lapsed", 0):,}', "gone quiet"),
        stat(f'{s.get("winback", 0):,}', "worth a nudge"),
        stat(_money(s.get("ltv", 0)), "lifetime value"),
    ])
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Store Concierge · Your desk</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='17' font-size='22' text-anchor='middle' dominant-baseline='central'>&#128206;</text></svg>">
<style>
  :root{{--white:#fff;--tint:#F4F4F4;--ink:#000;--soft:#3D3D3D;--faint:#8A8A8A;
    --plum:#5C3B54;--plum-deep:#3B2436;--line:rgba(0,0,0,.14);--line-2:rgba(0,0,0,.08);
    --f:'Helvetica Neue',Helvetica,Arial,sans-serif;--red:#8E2F3C;--green:#2E5D4B}}
  *{{box-sizing:border-box;margin:0;padding:0;font-style:normal}}
  body{{background:var(--white);color:var(--ink);font-family:var(--f);line-height:1.5;-webkit-font-smoothing:antialiased}}
  a{{color:inherit;text-decoration:none}}
  .wrap{{max-width:1120px;margin:0 auto;padding:0 24px}}
  header{{border-bottom:1px solid var(--line)}}
  header .bar{{display:flex;align-items:center;justify-content:space-between;height:66px}}
  .logo{{display:inline-flex;align-items:center;gap:9px;font-weight:600;font-size:19px;letter-spacing:-.01em}}
  header .who{{font-size:13px;color:var(--faint)}}
  .demo{{background:var(--plum);color:#fff;font-size:13px;text-align:center;padding:9px 16px;letter-spacing:.01em}}
  h1{{font-weight:600;font-size:clamp(24px,3.4vw,34px);letter-spacing:-.02em;margin:34px 0 6px}}
  .sub{{color:var(--soft);font-size:15px;margin-bottom:28px}}
  .stats{{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--line);border-right:0;margin-bottom:34px}}
  @media(max-width:720px){{.stats{{grid-template-columns:1fr 1fr}}}}
  .stat{{border-right:1px solid var(--line);padding:20px 22px}}
  .stat .n{{font-size:clamp(22px,3vw,30px);font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
  .stat .l{{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-top:6px}}
  .tabs{{display:flex;gap:0;border-bottom:1px solid var(--line);margin-bottom:0}}
  .tab{{padding:13px 22px;font-weight:600;font-size:14.5px;color:var(--faint);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}}
  .tab.on{{color:var(--ink);border-bottom-color:var(--plum)}}
  .toolbar{{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:16px 0;flex-wrap:wrap}}
  .toolbar input{{border:1px solid var(--line);padding:10px 14px;font:15px var(--f);min-width:240px;outline:none}}
  .toolbar input:focus{{border-color:var(--ink)}}
  .toolbar .hint{{font-size:13px;color:var(--faint)}}
  table{{width:100%;border-collapse:collapse;font-size:14.5px}}
  thead th{{text-align:left;font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);
    font-weight:600;padding:10px 14px;border-bottom:1px solid var(--line)}}
  thead th.num{{text-align:right}}
  tbody td{{padding:14px;border-bottom:1px solid var(--line-2);vertical-align:top}}
  tbody td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  tbody tr:hover{{background:var(--tint)}}
  td.nm{{font-weight:600}}
  td.nm .em{{display:block;font-weight:400;font-size:12.5px;color:var(--faint);margin-top:2px}}
  td .ago{{display:block;font-size:12px;color:var(--faint);margin-top:2px}}
  .pill{{font-size:12px;font-weight:600;padding:3px 10px;border:1px solid var(--line)}}
  .pill.active{{color:var(--green);border-color:var(--green)}}
  .pill.lapsed{{color:var(--red);border-color:var(--red)}}
  td.act a{{color:var(--plum);font-weight:600}}
  td.empty{{text-align:center;color:var(--faint);padding:40px}}
  .panel{{display:none}}.panel.on{{display:block}}
  footer{{border-top:1px solid var(--line);margin-top:50px;padding:26px 0;font-size:13px;color:var(--faint)}}
</style></head><body>
{banner}
<header><div class="wrap bar">
  <a class="logo" href="/storeconcierge">&#128206; Store Concierge</a>
  <span class="who">Your desk</span>
</div></header>

<div class="wrap">
  <h1>Your customers</h1>
  <div class="sub">Everyone who's shopped with you, and the ones worth a gentle hello.</div>
  <div class="stats">{stats}</div>

  <div class="tabs">
    <div class="tab on" data-tab="all">All customers</div>
    <div class="tab" data-tab="winback">Worth a nudge</div>
  </div>

  <div class="panel on" id="p-all">
    <div class="toolbar">
      <input id="q" placeholder="Search a name or email…" autocomplete="off">
      <span class="hint">Sorted by lifetime value</span>
    </div>
    <table><thead><tr>
      <th>Customer</th><th class="num">Orders</th><th class="num">Spent</th><th>Last order</th><th>Status</th><th></th>
    </tr></thead><tbody id="rows-all">{_rows(payload.get("customers", []))}</tbody></table>
  </div>

  <div class="panel" id="p-winback">
    <div class="toolbar">
      <span class="hint">Good customers who've gone quiet. A note goes a long way.</span>
    </div>
    <table><thead><tr>
      <th>Customer</th><th class="num">Orders</th><th class="num">Spent</th><th>Last order</th><th>Status</th><th></th>
    </tr></thead><tbody>{_rows(payload.get("winback", []), winback=True)}</tbody></table>
  </div>
</div>

<footer><div class="wrap">Store Concierge reads your orders to help you look after customers. It keeps nothing. A product of Midnight Lantern Technologies Ltd.</div></footer>

<script>
  var tabs=document.querySelectorAll('.tab'),panels={{all:document.getElementById('p-all'),winback:document.getElementById('p-winback')}};
  tabs.forEach(function(t){{t.onclick=function(){{
    tabs.forEach(function(x){{x.classList.remove('on')}});t.classList.add('on');
    for(var k in panels)panels[k].classList.toggle('on',k===t.dataset.tab);
  }};}});
  var q=document.getElementById('q');
  if(q)q.oninput=function(){{
    var v=q.value.trim().toLowerCase();
    document.querySelectorAll('#rows-all tr').forEach(function(r){{
      var hit=!v||(r.dataset.name||'').indexOf(v)>-1||(r.dataset.email||'').indexOf(v)>-1;
      r.style.display=hit?'':'none';
    }});
  }};
</script>
</body></html>"""
