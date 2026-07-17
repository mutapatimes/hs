"""Render the Store Concierge clienteling desk from a clienteling payload.

Three views: Clients, Orders (by lifecycle stage), and Win-back. Every row carries a template
picker and two one-tap send buttons, email and WhatsApp. The links are built in the browser
from the merchant's own mail client / WhatsApp; nothing is sent through us and nothing stored.
The look is Store Concierge's own: white, squared, Helvetica, plum. No scores, no grades.
"""
from __future__ import annotations

import html as _html
import json as _json

from halia.storeconcierge.messaging import (
    MOMENTS, suggest_for_stage, suggest_for_status, templates_public,
)


def _money(v) -> str:
    try:
        return "£" + f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "£0"


def _ago(days: int) -> str:
    return "today" if days <= 0 else (f"{days} days ago" if days < 400 else "over a year ago")


def _a(s) -> str:
    return _html.escape(str(s or ""), quote=True)


def _tselect(selected: str) -> str:
    opts = "".join(
        f'<option value="{m["key"]}"{" selected" if m["key"] == selected else ""}>{_html.escape(m["label"])}</option>'
        for m in MOMENTS
    )
    return f'<select class="tsel" aria-label="Message template">{opts}</select>'


def _actions(default_key: str) -> str:
    return (f'<div class="send">{_tselect(default_key)}'
            f'<button class="sb email" data-send="email">Email</button>'
            f'<button class="sb wa" data-send="whatsapp">WhatsApp</button></div>')


def _data_attrs(c: dict) -> str:
    q = f'{c.get("name", "")} {c.get("email", "")}'.lower()
    return (f'data-name="{_a(c.get("name"))}" data-email="{_a(c.get("email"))}" '
            f'data-phone="{_a(c.get("phone"))}" data-q="{_a(q)}"')


def _client_rows(rows: list, *, winback: bool = False) -> str:
    out = []
    for c in rows:
        status = "lapsed" if c.get("status") == "lapsed" else "active"
        default = "winback" if winback else suggest_for_status(status)
        out.append(
            f"<tr {_data_attrs(c)}>"
            f'<td class="nm">{_a(c.get("name")) or "Customer"}<span class="em">{_a(c.get("email")) or "no email on file"}</span></td>'
            f'<td class="num">{int(c.get("orders", 0))}</td>'
            f'<td class="num">{_money(c.get("spent", 0))}</td>'
            f'<td>{_a(c.get("last")) or "&mdash;"}<span class="ago">{_ago(int(c.get("days", 0)))}</span></td>'
            f'<td><span class="pill {status}">{status}</span></td>'
            f'<td class="act">{_actions(default)}</td>'
            f"</tr>"
        )
    return "".join(out) or '<tr><td colspan="6" class="empty">No customers here yet.</td></tr>'


def _order_rows(rows: list) -> str:
    out = []
    for c in rows:
        stage = c.get("stage", "delivered")
        cls = {"preparing": "prep", "on its way": "ship", "delivered": "deliv"}.get(stage, "deliv")
        default = suggest_for_stage(stage)
        out.append(
            f"<tr {_data_attrs(c)}>"
            f'<td class="nm">{_a(c.get("name")) or "Customer"}<span class="em">{_a(c.get("email")) or "no email on file"}</span></td>'
            f'<td><span class="stage {cls}">{_a(stage)}</span></td>'
            f'<td>{_a(c.get("last")) or "&mdash;"}<span class="ago">{_ago(int(c.get("days", 0)))}</span></td>'
            f'<td class="num">{_money(c.get("spent", 0))}</td>'
            f'<td class="act">{_actions(default)}</td>'
            f"</tr>"
        )
    return "".join(out) or '<tr><td colspan="5" class="empty">No recent orders.</td></tr>'


def render_clienteling(payload: dict, *, shop: str = "", demo: bool = False) -> str:
    s = payload.get("stats", {})
    shop = shop or "your shop"
    banner = ('<div class="demo">Sample data from a fictional shop. This is what your desk looks like.</div>'
              if demo else "")
    stat = lambda n, l: f'<div class="stat"><div class="n">{n}</div><div class="l">{l}</div></div>'
    stats = "".join([
        stat(f'{s.get("customers", 0):,}', "customers"),
        stat(f'{s.get("orders", 0):,}', "open orders"),
        stat(f'{s.get("lapsed", 0):,}', "gone quiet"),
        stat(f'{s.get("winback", 0):,}', "worth a nudge"),
        stat(_money(s.get("ltv", 0)), "lifetime value"),
    ])
    tmpl_json = _json.dumps({m["key"]: {"subject": m["subject"], "body": m["body"]}
                            for m in templates_public()})
    shop_json = _json.dumps(shop)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Store Concierge · Your desk</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='17' font-size='22' text-anchor='middle' dominant-baseline='central'>&#128206;</text></svg>">
<style>
  :root{{--white:#fff;--tint:#F4F4F4;--ink:#000;--soft:#3D3D3D;--faint:#8A8A8A;
    --plum:#5C3B54;--plum-deep:#3B2436;--line:rgba(0,0,0,.14);--line-2:rgba(0,0,0,.08);
    --f:'Helvetica Neue',Helvetica,Arial,sans-serif;--red:#8E2F3C;--green:#2E5D4B;--amber:#8A6D1F}}
  *{{box-sizing:border-box;margin:0;padding:0;font-style:normal}}
  body{{background:var(--white);color:var(--ink);font-family:var(--f);line-height:1.5;-webkit-font-smoothing:antialiased}}
  a{{color:inherit;text-decoration:none}}
  .wrap{{max-width:1180px;margin:0 auto;padding:0 24px}}
  header{{border-bottom:1px solid var(--line)}}
  header .bar{{display:flex;align-items:center;justify-content:space-between;height:66px}}
  .logo{{display:inline-flex;align-items:center;gap:9px;font-weight:600;font-size:19px;letter-spacing:-.01em}}
  header .who{{font-size:13px;color:var(--faint)}}
  .demo{{background:var(--plum);color:#fff;font-size:13px;text-align:center;padding:9px 16px}}
  h1{{font-weight:600;font-size:clamp(24px,3.4vw,34px);letter-spacing:-.02em;margin:34px 0 6px}}
  .sub{{color:var(--soft);font-size:15px;margin-bottom:28px}}
  .stats{{display:grid;grid-template-columns:repeat(5,1fr);border:1px solid var(--line);border-right:0;margin-bottom:34px}}
  @media(max-width:720px){{.stats{{grid-template-columns:1fr 1fr}}}}
  .stat{{border-right:1px solid var(--line);padding:20px 22px}}
  .stat .n{{font-size:clamp(22px,3vw,30px);font-weight:600;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
  .stat .l{{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-top:6px}}
  .tabs{{display:flex;border-bottom:1px solid var(--line)}}
  .tab{{padding:13px 22px;font-weight:600;font-size:14.5px;color:var(--faint);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}}
  .tab.on{{color:var(--ink);border-bottom-color:var(--plum)}}
  .toolbar{{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:16px 0;flex-wrap:wrap}}
  .toolbar input{{border:1px solid var(--line);padding:10px 14px;font:15px var(--f);min-width:240px;outline:none}}
  .toolbar input:focus{{border-color:var(--ink)}}
  .toolbar .hint{{font-size:13px;color:var(--faint)}}
  .tscroll{{overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:14.5px;min-width:720px}}
  thead th{{text-align:left;font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint);
    font-weight:600;padding:10px 14px;border-bottom:1px solid var(--line)}}
  thead th.num{{text-align:right}}
  tbody td{{padding:13px 14px;border-bottom:1px solid var(--line-2);vertical-align:middle}}
  tbody td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  tbody tr:hover{{background:var(--tint)}}
  td.nm{{font-weight:600}}
  td.nm .em{{display:block;font-weight:400;font-size:12.5px;color:var(--faint);margin-top:2px}}
  td .ago{{display:block;font-size:12px;color:var(--faint);margin-top:2px}}
  .pill{{font-size:12px;font-weight:600;padding:3px 10px;border:1px solid var(--line);white-space:nowrap}}
  .pill.active{{color:var(--green);border-color:var(--green)}}
  .pill.lapsed{{color:var(--red);border-color:var(--red)}}
  .stage{{font-size:12px;font-weight:600;padding:3px 10px;border:1px solid var(--line);white-space:nowrap}}
  .stage.prep{{color:var(--amber);border-color:var(--amber)}}
  .stage.ship{{color:var(--plum);border-color:var(--plum)}}
  .stage.deliv{{color:var(--green);border-color:var(--green)}}
  .send{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
  .tsel{{border:1px solid var(--line);padding:7px 9px;font:13px var(--f);background:#fff;cursor:pointer;outline:none;max-width:190px}}
  .tsel:focus{{border-color:var(--ink)}}
  .sb{{border:1px solid var(--plum);background:#fff;color:var(--plum);font:600 12.5px var(--f);padding:7px 12px;cursor:pointer;white-space:nowrap}}
  .sb:hover{{background:var(--plum);color:#fff}}
  .sb.wa{{border-color:var(--green);color:var(--green)}}
  .sb.wa:hover{{background:var(--green);color:#fff}}
  td.empty{{text-align:center;color:var(--faint);padding:40px}}
  .cat-head{{display:grid;grid-template-columns:1.1fr .9fr;gap:48px;align-items:center;padding:34px 0}}
  @media(max-width:760px){{.cat-head{{grid-template-columns:1fr;gap:28px}}}}
  .cat-h2{{font-size:clamp(22px,3vw,30px);font-weight:600;letter-spacing:-.02em}}
  .cat-p{{color:var(--soft);font-size:15.5px;margin:14px 0 24px;max-width:46ch}}
  .cat-btn{{display:inline-block;border:1px solid var(--plum);background:var(--plum);color:#fff;font-weight:600;font-size:14.5px;padding:13px 24px}}
  .cat-btn:hover{{background:var(--plum-deep);border-color:var(--plum-deep)}}
  .cat-card{{display:block;border:1px solid var(--line)}}
  .cat-card:hover{{border-color:var(--ink)}}
  .cat-thumb{{aspect-ratio:16/10;overflow:hidden}}
  .cat-thumb img{{width:100%;height:100%;object-fit:cover}}
  .cat-meta{{padding:16px 18px}}
  .cat-meta b{{display:block;font-weight:600}}
  .cat-meta span{{font-size:13px;color:var(--faint)}}
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
  <div class="sub">Look after everyone who shops with you. Pick a message, send it by email or WhatsApp.</div>
  <div class="stats">{stats}</div>

  <div class="tabs">
    <div class="tab on" data-tab="clients">Clients</div>
    <div class="tab" data-tab="orders">Orders</div>
    <div class="tab" data-tab="winback">Worth a nudge</div>
    <div class="tab" data-tab="catalogues">Catalogues</div>
  </div>

  <div class="panel on" id="p-clients">
    <div class="toolbar">
      <input id="q" placeholder="Search a name or email…" autocomplete="off">
      <span class="hint">Sorted by lifetime value</span>
    </div>
    <div class="tscroll"><table><thead><tr>
      <th>Customer</th><th class="num">Orders</th><th class="num">Spent</th><th>Last order</th><th>Status</th><th>Message</th>
    </tr></thead><tbody id="rows-clients">{_client_rows(payload.get("customers", []))}</tbody></table></div>
  </div>

  <div class="panel" id="p-orders">
    <div class="toolbar"><span class="hint">Recent orders, by stage. Send the right note for where each one is.</span></div>
    <div class="tscroll"><table><thead><tr>
      <th>Customer</th><th>Stage</th><th>Ordered</th><th class="num">Order value</th><th>Message</th>
    </tr></thead><tbody>{_order_rows(payload.get("orders", []))}</tbody></table></div>
  </div>

  <div class="panel" id="p-winback">
    <div class="toolbar"><span class="hint">Good customers who've gone quiet. A warm note goes a long way.</span></div>
    <div class="tscroll"><table><thead><tr>
      <th>Customer</th><th class="num">Orders</th><th class="num">Spent</th><th>Last order</th><th>Status</th><th>Message</th>
    </tr></thead><tbody>{_client_rows(payload.get("winback", []), winback=True)}</tbody></table></div>
  </div>

  <div class="panel" id="p-catalogues">
    <div class="cat-head">
      <div>
        <h2 class="cat-h2">A private selection, sent as a link.</h2>
        <p class="cat-p">Pick pieces from your shop, add a personal line, and share a beautiful
        page. Your customer ticks what they like and the enquiry lands in your inbox. Send the
        same link by email or WhatsApp from any client on the desk.</p>
        <a class="cat-btn" href="/storeconcierge/catalogue-demo" target="_blank" rel="noopener">Open a sample catalogue &rsaquo;</a>
      </div>
      <a class="cat-card" href="/storeconcierge/catalogue-demo" target="_blank" rel="noopener">
        <div class="cat-thumb"><img src="img/luxurybag.jpg" alt="A catalogue selection"></div>
        <div class="cat-meta"><b>A private selection for Grace</b><span>6 pieces &middot; share link ready</span></div>
      </a>
    </div>
  </div>
</div>

<footer><div class="wrap">Store Concierge reads your orders to help you look after customers. It keeps nothing. A product of Midnight Lantern Technologies Ltd.</div></footer>

<script>
  var TEMPLATES={tmpl_json}, SHOP={shop_json};
  function firstName(n){{return (String(n||'').trim().split(' ')[0])||'there';}}
  function fill(s,n){{return String(s||'').split('{{first_name}}').join(firstName(n)).split('{{shop}}').join(SHOP);}}
  function waNum(p){{var d=String(p||'').replace(/\\D/g,'');if(d.indexOf('00')===0)d=d.slice(2);return d;}}

  // tabs
  var tabs=document.querySelectorAll('.tab');
  var panels={{clients:document.getElementById('p-clients'),orders:document.getElementById('p-orders'),winback:document.getElementById('p-winback'),catalogues:document.getElementById('p-catalogues')}};
  tabs.forEach(function(t){{t.onclick=function(){{
    tabs.forEach(function(x){{x.classList.remove('on')}});t.classList.add('on');
    for(var k in panels)panels[k].classList.toggle('on',k===t.dataset.tab);
  }};}});

  // search (clients)
  var q=document.getElementById('q');
  if(q)q.oninput=function(){{
    var v=q.value.trim().toLowerCase();
    document.querySelectorAll('#rows-clients tr').forEach(function(r){{
      r.style.display=(!v||(r.dataset.q||'').indexOf(v)>-1)?'':'none';
    }});
  }};

  // one-tap send: build the email / WhatsApp link from the chosen template
  document.addEventListener('click',function(e){{
    var b=e.target.closest('[data-send]'); if(!b)return;
    var tr=b.closest('tr'); if(!tr)return;
    var sel=tr.querySelector('.tsel'); var t=TEMPLATES[sel&&sel.value];
    if(!t)return;
    var name=tr.dataset.name, body=fill(t.body,name), subj=fill(t.subject,name);
    if(b.dataset.send==='email'){{
      var em=tr.dataset.email;
      if(!em){{alert('No email on file for this customer.');return;}}
      location.href='mailto:'+em+'?subject='+encodeURIComponent(subj)+'&body='+encodeURIComponent(body);
    }}else{{
      var num=waNum(tr.dataset.phone);
      if(!num){{alert('No usable phone number for WhatsApp.');return;}}
      window.open('https://wa.me/'+num+'?text='+encodeURIComponent(body),'_blank');
    }}
  }});
</script>
</body></html>"""
