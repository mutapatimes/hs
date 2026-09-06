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
_ZERO_DECIMAL = {"JPY", "KRW"}


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
    if cur in _ZERO_DECIMAL:                       # yen (and won) carry no minor unit
        return f"{sym}{v:,.0f}" if sym else f"{v:,.0f} {cur}".strip()
    return f"{sym}{v:,.2f}" if sym else (f"{v:,.2f} {cur}".strip())


def _desc(p: dict, limit: int = 220) -> str:
    raw = _re.sub(r"\s+", " ", str(p.get("description") or "")).strip()
    if len(raw) > limit:
        raw = raw[:limit].rsplit(" ", 1)[0].rstrip(",.;: ") + "…"
    return raw


def _card(p: dict, brand: str, fields: dict, pick_label: str = "Pick") -> str:
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
            f'<span class="pi">+</span><span class="pl">{_esc(pick_label)}</span></button></div>')


def _social_tags(title: str, desc: str, image: str, site: str) -> str:
    """Preview tags, so a pasted link renders as an image card in iMessage, WhatsApp, Instagram and
    Slack. Only an https image is offered: a data: logo would be dropped by every unfurler, and a
    card with a broken image reads worse than a card with none."""
    img = image if str(image or "").startswith("https://") else ""
    out = ['<meta property="og:type" content="website">',
           f'<meta property="og:title" content="{_attr(title)}">',
           f'<meta name="twitter:card" content="{"summary_large_image" if img else "summary"}">']
    if site:
        out.append(f'<meta property="og:site_name" content="{_attr(site)}">')
    if desc:
        out.append(f'<meta property="og:description" content="{_attr(desc)}">')
        out.append(f'<meta name="twitter:description" content="{_attr(desc)}">')
    if img:
        out.append(f'<meta property="og:image" content="{_attr(img)}">')
        out.append(f'<meta name="twitter:image" content="{_attr(img)}">')
    return "\n".join(out)


def catalog_form_html(catalog: dict, products: list[dict], *, shop_name: str, catalog_id: str,
                      enquiry_email: str, prefill: dict | None = None,
                      og_image: str = "", og_desc: str = "", by: str = "",
                      lang: str = "en") -> str:
    """Full interactive enquiry page. ``prefill`` may carry name/email/phone from the share link;
    ``by`` is the seat that sent it, so their picks come back to that associate. ``lang`` is the
    store's client language (halia.i18n); everything the client reads follows it."""
    from halia.i18n import font_prefix, t as _t
    def T(key, **fmt):
        return _t(lang, key, **fmt)
    prefill = prefill or {}
    name = catalog.get("name") or T("cat.title_fallback")
    personal = str(catalog.get("subtitle") or "").strip()   # personalised line, already token-filled
    logo = str(catalog.get("logo") or "").strip()           # retailer logo (data: URI or URL)
    brand = catalog.get("brand_color") or "#1f564a"
    fields = catalog.get("fields") or {}
    cards = "".join(_card(p, brand, fields, T("cat.pick")) for p in products) \
        or f'<div class="empty">{_esc(T("cat.empty"))}</div>'
    subtitle = _esc(shop_name) if shop_name else _esc(T("cat.site_fallback"))
    return f"""<!doctype html><html lang="{lang}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{_esc(name)}{f' · {_esc(shop_name)}' if shop_name else ''}</title>
{_social_tags(name, og_desc, og_image, shop_name)}
<style>
  :root {{ --brand: {brand}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #fafafa; color: #1a1712;
    font-family: {font_prefix(lang)}'Helvetica', Arial, sans-serif; }}
  a {{ color: #1a1712; }}
  .wrap {{ max-width: 1120px; margin: 0 auto; padding: 0 22px; }}
  header {{ padding: 54px 0 30px; border-bottom: 1px solid #ece8df; margin-bottom: 30px; }}
  .logo {{ max-height: 48px; max-width: 220px; object-fit: contain; margin-bottom: 18px; display: block; }}
  .eyebrow {{ font: 600 11px 'Helvetica', Arial, sans-serif; letter-spacing: .22em; text-transform: uppercase; color: #8a857a; }}
  h1 {{ font: 400 34px 'Helvetica', Arial, sans-serif; letter-spacing: -.3px; margin: 12px 0 8px; line-height: 1.1; }}
  .personal {{ font-style: italic; font-size: 18px; color: #6b6557; margin: 4px 0 10px; }}
  .lead {{ color: #6b6557; font-size: 15px; max-width: 60ch; line-height: 1.55; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 26px 20px;
    padding-bottom: 140px; }}
  .card {{ display: flex; flex-direction: column; border: 1px solid #e6e6e3; border-radius:0;
    overflow: hidden; background: #fff; transition: box-shadow .2s, border-color .2s; }}
  .card.on {{ border-color: #1a1712; box-shadow: 0 12px 30px -18px rgba(0,0,0,.35); }}
  .ph {{ aspect-ratio: 4/5; background: #f4f4f2 center/cover no-repeat; }}
  .ph.noimg {{ background: #f0f0ee; }}
  .meta {{ padding: 13px 15px 6px; flex: 1; }}
  .vendor {{ font: 600 10px 'Helvetica', Arial, sans-serif; letter-spacing: .1em; text-transform: uppercase; color: #9a9385; }}
  .title {{ font: 400 17px 'Helvetica', Arial, sans-serif; margin: 3px 0 5px; line-height: 1.25; }}
  .price {{ font: 600 14px 'Helvetica', Arial, sans-serif; color: #1a1712; }}
  .cdesc {{ font-size: 12.5px; line-height: 1.5; color: #6b6557; margin-top: 7px; }}
  .pick {{ margin: 10px 13px 14px; padding: 9px 12px; border-radius:0; cursor: pointer;
    border: 1px solid #1a1712; background: #fff; color: #1a1712;
    font: 600 13px 'Helvetica', Arial, sans-serif; display: flex; align-items: center; justify-content: center; gap: 7px; }}
  .card.on .pick {{ background: #1a1712; color: #fff; }}
  .card.on .pick .pi {{ transform: rotate(45deg); }}
  .pick .pi {{ font-size: 16px; line-height: 1; transition: transform .2s; }}
  .empty {{ color: #9a9385; padding: 40px; text-align: center; grid-column: 1/-1; }}
  /* sticky action bar */
  .bar {{ position: fixed; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,.94);
    backdrop-filter: blur(8px); border-top: 1px solid #e6e2d8; padding: 14px 0;
    transform: translateY(120%); transition: transform .3s cubic-bezier(.2,.7,.2,1); z-index: 40; }}
  .bar.show {{ transform: none; }}
  .bar .wrap {{ display: flex; align-items: center; gap: 16px; }}
  .bar .n {{ font: 500 14px 'Helvetica', Arial, sans-serif; color: #1a1712; }}
  .btn {{ border: none; border-radius:0; padding: 12px 26px; cursor: pointer;
    font: 600 14px 'Helvetica', Arial, sans-serif; background: #1a1712; color: #fff; }}
  .btn.ghost {{ background: transparent; color: #1a1712; border: 1px solid #1a1712; }}
  .btn:disabled {{ opacity: .55; cursor: default; }}
  /* enquiry panel */
  .panel {{ position: fixed; inset: 0; background: rgba(20,18,12,.42); display: none;
    align-items: flex-end; justify-content: center; z-index: 50; }}
  .panel.show {{ display: flex; }}
  .sheet {{ background: #fff; width: 100%; max-width: 560px; border-radius:0;
    padding: 26px 26px 30px; max-height: 92vh; overflow-y: auto; }}
  @media(min-width: 640px) {{ .panel {{ align-items: center; }} .sheet {{ border-radius:0; }} }}
  .sheet h2 {{ font: 500 23px 'Helvetica', Arial, sans-serif; margin: 0 0 4px; }}
  .sheet p.sub {{ color: #6b6557; font-size: 13.5px; margin: 0 0 18px; }}
  .field {{ margin-bottom: 13px; }}
  .field label {{ display: block; font: 600 12px 'Helvetica', Arial, sans-serif; color: #6b6557; margin-bottom: 5px; }}
  .field input, .field textarea {{ width: 100%; padding: 11px 13px; border: 1px solid #d8d4c8;
    border-radius:0; font: 14px 'Helvetica', Arial, sans-serif; color: #1a1712; background: #fff; outline: none; }}
  .field input:focus, .field textarea:focus {{ border-color: #1a1712; }}
  .picked {{ background: #f6f4ee; border: 1px solid #ece8df; border-radius:0; padding: 12px 14px;
    margin-bottom: 16px; font-size: 13px; color: #4a463e; max-height: 160px; overflow-y: auto; }}
  .picked b {{ color: #1a1712; }}
  .hp {{ position: absolute; left: -9999px; }}
  .ok {{ text-align: center; padding: 22px 6px; }}
  .ok .tick {{ width: 54px; height: 54px; border-radius:0; background: #1a1712; color: #fff;
    font-size: 26px; display: flex; align-items: center; justify-content: center; margin: 0 auto 16px; }}
</style></head><body>
<div class="wrap">
  <header>
    {f'<img class="logo" src="{_attr(logo)}" alt="">' if logo else ''}
    <div class="eyebrow">{subtitle}</div>
    <h1>{_esc(name)}</h1>
    {f'<p class="personal">{_esc(personal)}</p>' if personal else ''}
    <p class="lead">{_esc(T("cat.lead"))}</p>
  </header>
  <div class="grid" id="grid">{cards}</div>
</div>

<div class="bar" id="bar"><div class="wrap">
  <span class="n"><b id="barN">0</b> {_esc(T("cat.selected"))}</span>
  <span style="flex:1"></span>
  <button type="button" class="btn ghost" id="clearBtn">{_esc(T("cat.clear"))}</button>
  <button type="button" class="btn" id="openBtn">{_esc(T("cat.continue"))}</button>
</div></div>

<div class="panel" id="panel"><div class="sheet" id="sheet">
  <form id="enqForm">
    <h2>{_esc(T("cat.sheet_title"))}</h2>
    <div class="picked" id="pickedList"></div>
    <div class="field"><label>{_esc(T("cat.name"))}</label><input name="name" required value="{_attr(prefill.get('name',''))}" placeholder="{_attr(T("cat.name_ph"))}"></div>
    <div class="field"><label>{_esc(T("cat.email"))}</label><input name="email" type="email" required value="{_attr(prefill.get('email',''))}" placeholder="you@email.com"></div>
    <div class="field"><label>{_esc(T("cat.phone"))}</label><input name="phone" value="{_attr(prefill.get('phone',''))}" placeholder="{_attr(T("cat.phone_ph"))}"></div>
    <div class="field"><label>{_esc(T("cat.message"))}</label><textarea name="message" rows="3" placeholder="{_attr(T("cat.message_ph"))}"></textarea></div>
    <input class="hp" name="company" tabindex="-1" autocomplete="off" aria-hidden="true">
    <input type="hidden" name="by" value="{_attr(by)}">
    <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:6px">
      <button type="button" class="btn ghost" id="cancelBtn">{_esc(T("cat.back"))}</button>
      <button type="submit" class="btn" id="sendBtn">{_esc(T("cat.send"))}</button>
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
    if(selected.has(id)){{ selected.delete(id); card.classList.remove('on'); b.querySelector('.pl').textContent={_jstr(T("cat.pick"))}; }}
    else {{ selected.add(id); card.classList.add('on'); b.querySelector('.pl').textContent={_jstr(T("cat.picked"))}; }}
    refresh();
  }});
  document.getElementById('clearBtn').onclick=function(){{
    selected.clear();
    grid.querySelectorAll('.card.on').forEach(function(c){{ c.classList.remove('on'); c.querySelector('.pl').textContent={_jstr(T("cat.pick"))}; }});
    refresh();
  }};
  function openPanel(){{
    var list=document.getElementById('pickedList'), rows=[];
    grid.querySelectorAll('.card').forEach(function(c){{
      if(selected.has(c.getAttribute('data-pid'))) rows.push('<div>• <b>'+ (c.getAttribute('data-title')||'') +'</b></div>');
    }});
    var pickedLine=(rows.length>1?{_jstr(T("cat.picked_n", n="__N__", s="s"))}:{_jstr(T("cat.picked_n", n="__N__", s=""))}).replace('__N__', rows.length);
    list.innerHTML = rows.length ? (pickedLine+'<div style="margin-top:6px">'+rows.join('')+'</div>') : {_jstr(T("cat.none_yet"))};
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
      message:f.message.value.trim(), company:f.company.value, by:(f.by&&f.by.value)||'' }};
    if(!payload.name || !payload.email){{ err.textContent={_jstr(T("cat.err_need"))}; err.style.display='block'; return; }}
    btn.disabled=true; btn.textContent={_jstr(T("cat.sending"))};
    // POST relative to how this page was served, so it works both directly and under the App Proxy
    // (theirbrand.com/a/catalogue/{{id}} -> …/{{id}}/enquire), never hard-coding an app URL. The
    // query string comes along: a bespoke selection is signed there, and the App Proxy signs there.
    var enquireUrl = window.location.pathname.replace(/\\/+$/, '') + '/enquire' + window.location.search;
    fetch(enquireUrl, {{ method:'POST', headers:{{'content-type':'application/json'}}, body:JSON.stringify(payload) }})
      .then(function(r){{ return r.json().then(function(d){{ return {{ok:r.ok, d:d}}; }}); }})
      .then(function(res){{
        if(!res.ok) throw new Error((res.d&&res.d.detail)||{_jstr(T("cat.err_send"))});
        document.getElementById('sheet').innerHTML='<div class="ok"><div class="tick">✓</div>'
          +'<h2 style="margin:0 0 6px">'+{_jstr(T("cat.sent"))}+'</h2>'
          +'<p class="sub" style="margin:0">'+{_jstr(T("cat.thanks"))}+'</p></div>';
      }})
      .catch(function(ex){{ err.textContent=ex.message; err.style.display='block'; btn.disabled=false; btn.textContent={_jstr(T("cat.send"))}; }});
  }});
}})();
</script>
</body></html>"""


def _js(s: str) -> str:
    """A safe single-quoted JS string literal for a server-injected id."""
    return "'" + _re.sub(r"[^A-Za-z0-9_\-]", "", str(s)) + "'"


def _jstr(s: str) -> str:
    """A JS string literal for real copy. json.dumps escapes quotes and non-ASCII correctly;
    breaking "</" stops a </script> in a translation from ending the block early."""
    import json as _json
    return _json.dumps(str(s or ""), ensure_ascii=False).replace("</", "<\\/")
