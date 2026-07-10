"""The shareable, interactive version of a catalog: a web page styled like the catalogue where
the recipient ticks the products they want, fills a short form (name/email prefilled when the
merchant sends a personalised link), and submits. The enquiry is emailed straight to the merchant
and nothing about the recipient is stored (zero retention, by architecture).

Rendered server-side as one self-contained HTML document (no external assets), matching the repo's
f-string style (see halia/api/blog.py, halia/catalog_render.py).
"""
from __future__ import annotations

import html as _html
import re as _re

_CUR_SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$", "JPY": "¥", "AUD": "$", "CAD": "$"}


def _esc(s: object) -> str:
    return _html.escape(str(s if s is not None else ""))


def _attr(s: object) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def _price(p: dict) -> str:
    amt, cur = p.get("price"), p.get("currency") or ""
    if amt in (None, ""):
        return ""
    try:
        v = float(amt)
    except (TypeError, ValueError):
        return ""
    sym = _CUR_SYMBOL.get(cur)
    return f"{sym}{v:,.2f}" if sym else (f"{v:,.2f} {cur}".strip())


def _desc(p: dict, limit: int = 220) -> str:
    raw = _re.sub(r"\s+", " ", str(p.get("description") or "")).strip()
    if len(raw) > limit:
        raw = raw[:limit].rsplit(" ", 1)[0].rstrip(",.;: ") + "…"
    return raw


def _card(p: dict, brand: str, fields: dict) -> str:
    pid = _attr(p.get("id"))
    img = p.get("image_url")
    media = (f'<div class="ph" style="background-image:url(\'{_attr(img)}\')"></div>' if img
             else '<div class="ph noimg"></div>')
    bits = []
    if fields.get("vendor") and p.get("vendor"):
        bits.append(f'<div class="vendor">{_esc(p["vendor"])}</div>')
    bits.append(f'<div class="title">{_esc(p.get("title"))}</div>')
    if fields.get("price") and _price(p):
        bits.append(f'<div class="price">{_esc(_price(p))}</div>')
    if fields.get("description") and _desc(p):
        bits.append(f'<div class="cdesc">{_esc(_desc(p))}</div>')
    return (f'<div class="card" data-pid="{pid}" data-title="{_attr(p.get("title"))}">'
            f'{media}<div class="meta">{"".join(bits)}</div>'
            f'<button type="button" class="pick" data-pid="{pid}">'
            f'<span class="pi">+</span><span class="pl">Add to enquiry</span></button></div>')


def catalog_form_html(catalog: dict, products: list[dict], *, shop_name: str, catalog_id: str,
                      enquiry_email: str, prefill: dict | None = None) -> str:
    """Full interactive enquiry page. ``prefill`` may carry name/email/phone from the share link."""
    prefill = prefill or {}
    name = catalog.get("name") or "Product Catalogue"
    brand = catalog.get("brand_color") or "#1f564a"
    fields = catalog.get("fields") or {}
    cards = "".join(_card(p, brand, fields) for p in products) \
        or '<div class="empty">This catalogue has no products yet.</div>'
    subtitle = _esc(shop_name) if shop_name else "Catalogue"
    return f"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{_esc(name)}{f' · {_esc(shop_name)}' if shop_name else ''}</title>
<style>
  :root {{ --brand: {brand}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #faf9f6; color: #1a1712;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
  a {{ color: var(--brand); }}
  .wrap {{ max-width: 1120px; margin: 0 auto; padding: 0 22px; }}
  header {{ padding: 54px 0 30px; border-bottom: 1px solid #ece8df; margin-bottom: 30px; }}
  .eyebrow {{ font: 600 11px 'Inter'; letter-spacing: .26em; text-transform: uppercase; color: var(--brand); }}
  h1 {{ font: 300 40px Georgia, serif; margin: 12px 0 8px; line-height: 1.05; }}
  .lead {{ color: #6b6557; font-size: 15px; max-width: 60ch; line-height: 1.55; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 26px 20px;
    padding-bottom: 140px; }}
  .card {{ display: flex; flex-direction: column; border: 1px solid #e9e5db; border-radius: 14px;
    overflow: hidden; background: #fff; transition: box-shadow .2s, border-color .2s; }}
  .card.on {{ border-color: var(--brand); box-shadow: 0 12px 30px -18px rgba(0,0,0,.35); }}
  .ph {{ aspect-ratio: 4/5; background: #f2f0ea center/cover no-repeat; }}
  .ph.noimg {{ background: #efeadd; }}
  .meta {{ padding: 13px 15px 6px; flex: 1; }}
  .vendor {{ font: 600 10px 'Inter'; letter-spacing: .1em; text-transform: uppercase; color: #9a9385; }}
  .title {{ font: 400 17px Georgia, serif; margin: 3px 0 5px; line-height: 1.25; }}
  .price {{ font: 600 14px 'Inter'; color: var(--brand); }}
  .cdesc {{ font-size: 12.5px; line-height: 1.5; color: #6b6557; margin-top: 7px; }}
  .pick {{ margin: 10px 13px 14px; padding: 9px 12px; border-radius: 10px; cursor: pointer;
    border: 1px solid var(--brand); background: #fff; color: var(--brand);
    font: 600 13px 'Inter'; display: flex; align-items: center; justify-content: center; gap: 7px; }}
  .card.on .pick {{ background: var(--brand); color: #fff; }}
  .card.on .pick .pi {{ transform: rotate(45deg); }}
  .pick .pi {{ font-size: 16px; line-height: 1; transition: transform .2s; }}
  .empty {{ color: #9a9385; padding: 40px; text-align: center; grid-column: 1/-1; }}
  /* sticky action bar */
  .bar {{ position: fixed; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,.94);
    backdrop-filter: blur(8px); border-top: 1px solid #e6e2d8; padding: 14px 0;
    transform: translateY(120%); transition: transform .3s cubic-bezier(.2,.7,.2,1); z-index: 40; }}
  .bar.show {{ transform: none; }}
  .bar .wrap {{ display: flex; align-items: center; gap: 16px; }}
  .bar .n {{ font: 500 14px 'Inter'; color: #1a1712; }}
  .btn {{ border: none; border-radius: 999px; padding: 12px 26px; cursor: pointer;
    font: 600 14px 'Inter'; background: var(--brand); color: #fff; }}
  .btn.ghost {{ background: transparent; color: var(--brand); border: 1px solid var(--brand); }}
  .btn:disabled {{ opacity: .55; cursor: default; }}
  /* enquiry panel */
  .panel {{ position: fixed; inset: 0; background: rgba(20,18,12,.42); display: none;
    align-items: flex-end; justify-content: center; z-index: 50; }}
  .panel.show {{ display: flex; }}
  .sheet {{ background: #fff; width: 100%; max-width: 560px; border-radius: 18px 18px 0 0;
    padding: 26px 26px 30px; max-height: 92vh; overflow-y: auto; }}
  @media(min-width: 640px) {{ .panel {{ align-items: center; }} .sheet {{ border-radius: 18px; }} }}
  .sheet h2 {{ font: 300 26px Georgia, serif; margin: 0 0 4px; }}
  .sheet p.sub {{ color: #6b6557; font-size: 13.5px; margin: 0 0 18px; }}
  .field {{ margin-bottom: 13px; }}
  .field label {{ display: block; font: 600 12px 'Inter'; color: #6b6557; margin-bottom: 5px; }}
  .field input, .field textarea {{ width: 100%; padding: 11px 13px; border: 1px solid #d8d4c8;
    border-radius: 10px; font: 14px 'Inter'; color: #1a1712; background: #fff; outline: none; }}
  .field input:focus, .field textarea:focus {{ border-color: var(--brand); }}
  .picked {{ background: #f6f4ee; border: 1px solid #ece8df; border-radius: 12px; padding: 12px 14px;
    margin-bottom: 16px; font-size: 13px; color: #4a463e; max-height: 160px; overflow-y: auto; }}
  .picked b {{ color: #1a1712; }}
  .hp {{ position: absolute; left: -9999px; }}
  .ok {{ text-align: center; padding: 22px 6px; }}
  .ok .tick {{ width: 54px; height: 54px; border-radius: 50%; background: var(--brand); color: #fff;
    font-size: 26px; display: flex; align-items: center; justify-content: center; margin: 0 auto 16px; }}
  .foot {{ text-align: center; color: #b6b1a5; font-size: 12px; padding: 20px 0 34px; }}
</style></head><body>
<div class="wrap">
  <header>
    <div class="eyebrow">{subtitle}</div>
    <h1>{_esc(name)}</h1>
    <p class="lead">Tick the pieces you would like to enquire about, then send. Your selection reaches
      the team directly and they will be in touch.</p>
  </header>
  <div class="grid" id="grid">{cards}</div>
  <div class="foot">Powered by Halia · your details are sent to the store and not stored here.</div>
</div>

<div class="bar" id="bar"><div class="wrap">
  <span class="n"><b id="barN">0</b> selected</span>
  <span style="flex:1"></span>
  <button type="button" class="btn ghost" id="clearBtn">Clear</button>
  <button type="button" class="btn" id="openBtn">Continue to enquiry →</button>
</div></div>

<div class="panel" id="panel"><div class="sheet" id="sheet">
  <form id="enqForm">
    <h2>Send your enquiry</h2>
    <p class="sub">Confirm your details and we will get back to you about the pieces you chose.</p>
    <div class="picked" id="pickedList"></div>
    <div class="field"><label>Your name</label><input name="name" required value="{_attr(prefill.get('name',''))}" placeholder="Full name"></div>
    <div class="field"><label>Email</label><input name="email" type="email" required value="{_attr(prefill.get('email',''))}" placeholder="you@email.com"></div>
    <div class="field"><label>Phone (optional)</label><input name="phone" value="{_attr(prefill.get('phone',''))}" placeholder="Best number to reach you"></div>
    <div class="field"><label>Message (optional)</label><textarea name="message" rows="3" placeholder="Anything you'd like the team to know"></textarea></div>
    <input class="hp" name="company" tabindex="-1" autocomplete="off" aria-hidden="true">
    <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:6px">
      <button type="button" class="btn ghost" id="cancelBtn">Back</button>
      <button type="submit" class="btn" id="sendBtn">Send enquiry</button>
    </div>
    <div id="formErr" style="color:#a23b2a;font-size:13px;margin-top:10px;display:none"></div>
  </form>
</div></div>

<script>
(function(){{
  var CAT_ID={_js(catalog_id)};
  var selected=new Set();
  var grid=document.getElementById('grid'), bar=document.getElementById('bar'), barN=document.getElementById('barN');
  var panel=document.getElementById('panel');
  function refresh(){{
    barN.textContent=selected.size;
    bar.classList.toggle('show', selected.size>0);
  }}
  grid.addEventListener('click', function(e){{
    var b=e.target.closest('.pick'); if(!b) return;
    var card=b.closest('.card'), id=b.getAttribute('data-pid');
    if(selected.has(id)){{ selected.delete(id); card.classList.remove('on'); b.querySelector('.pl').textContent='Add to enquiry'; }}
    else {{ selected.add(id); card.classList.add('on'); b.querySelector('.pl').textContent='Added'; }}
    refresh();
  }});
  document.getElementById('clearBtn').onclick=function(){{
    selected.clear();
    grid.querySelectorAll('.card.on').forEach(function(c){{ c.classList.remove('on'); c.querySelector('.pl').textContent='Add to enquiry'; }});
    refresh();
  }};
  function openPanel(){{
    var list=document.getElementById('pickedList'), rows=[];
    grid.querySelectorAll('.card').forEach(function(c){{
      if(selected.has(c.getAttribute('data-pid'))) rows.push('<div>• <b>'+ (c.getAttribute('data-title')||'') +'</b></div>');
    }});
    list.innerHTML = rows.length ? ('Enquiring about '+rows.length+' item'+(rows.length>1?'s':'')+':<div style="margin-top:6px">'+rows.join('')+'</div>') : 'No items selected yet.';
    panel.classList.add('show');
  }}
  document.getElementById('openBtn').onclick=openPanel;
  document.getElementById('cancelBtn').onclick=function(){{ panel.classList.remove('show'); }};
  panel.addEventListener('click', function(e){{ if(e.target===panel) panel.classList.remove('show'); }});
  document.getElementById('enqForm').addEventListener('submit', function(e){{
    e.preventDefault();
    var f=e.target, err=document.getElementById('formErr'), btn=document.getElementById('sendBtn');
    err.style.display='none';
    var payload={{ product_ids:[].concat.apply([],[Array.from(selected)]),
      name:f.name.value.trim(), email:f.email.value.trim(), phone:f.phone.value.trim(),
      message:f.message.value.trim(), company:f.company.value }};
    if(!payload.name || !payload.email){{ err.textContent='Please add your name and email.'; err.style.display='block'; return; }}
    btn.disabled=true; btn.textContent='Sending…';
    // POST relative to how this page was served, so it works both directly and under the App Proxy
    // (theirbrand.com/a/catalogue/{{id}} -> …/{{id}}/enquire), never hard-coding a Halia URL.
    var enquireUrl = window.location.pathname.replace(/\\/+$/, '') + '/enquire';
    fetch(enquireUrl, {{ method:'POST', headers:{{'content-type':'application/json'}}, body:JSON.stringify(payload) }})
      .then(function(r){{ return r.json().then(function(d){{ return {{ok:r.ok, d:d}}; }}); }})
      .then(function(res){{
        if(!res.ok) throw new Error((res.d&&res.d.detail)||'Could not send');
        document.getElementById('sheet').innerHTML='<div class="ok"><div class="tick">✓</div>'
          +'<h2 style="margin:0 0 6px">Enquiry sent</h2>'
          +'<p class="sub" style="margin:0">Thank you. The team has your selection and will be in touch shortly.</p></div>';
      }})
      .catch(function(ex){{ err.textContent=ex.message; err.style.display='block'; btn.disabled=false; btn.textContent='Send enquiry'; }});
  }});
}})();
</script>
</body></html>"""


def _js(s: str) -> str:
    """A safe single-quoted JS string literal for a server-injected id."""
    return "'" + _re.sub(r"[^A-Za-z0-9_\-]", "", str(s)) + "'"
