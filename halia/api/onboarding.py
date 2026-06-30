"""Self-service onboarding + hosted dashboard for non-Shopify clients (WooCommerce now).

A client connects their store at **/connect**: store URL + read-only WooCommerce REST keys
(plus the signup code, if one is configured). We validate the creds with one live read,
create a tenant with the creds encrypted, and hand back a private dashboard link
(**/app?t=<token>**). The dashboard pulls + scores in RAM (zero-retention) and shows their
hidden VICs + Settings. No env files, no engineer in the loop.

First load triggers a background sync (a full store pull can take a while) and shows a
"preparing" page that auto-refreshes; once the RAM cache is warm the dashboard renders.
"""
from __future__ import annotations

import html
import re
import threading
import traceback

from fastapi import Body, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from halia import config
from halia.api import data
from halia.api.shopify_auth import shop_store
from halia.api.tenant_auth import COOKIE, hash_token, new_token, require_tenant, resolve_tenant
from halia.cache import cache

# Shops currently being scored in a background thread (so we don't double-trigger).
_SYNCING: set[str] = set()
_LOCK = threading.Lock()

_CSS = (
    "body{margin:0;background:#f1f1f1;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',"
    "Roboto,Helvetica,Arial,sans-serif;color:#303030}.wrap{max-width:560px;margin:0 auto;"
    "padding:48px 20px 80px}.card{background:#fff;border:1px solid #e3e3e3;border-radius:12px;"
    "padding:24px}h1{font:650 24px system-ui;margin:0 0 6px}.sub{color:#616161;font-size:14px;"
    "margin:0 0 22px}label{display:block;font:600 13px system-ui;margin:14px 0 5px}"
    "input{width:100%;box-sizing:border-box;padding:9px 12px;border:1px solid #8a8a8a;"
    "border-radius:8px;font:14px system-ui}.help{font-size:12px;color:#616161;margin:4px 0 0}"
    ".btn{margin-top:22px;background:#303030;color:#fff;border:none;border-radius:8px;"
    "padding:12px 20px;font:600 14px system-ui;cursor:pointer}.err{background:#fff1f0;"
    "border:1px solid #e0b4b0;color:#8e1f0b;border-radius:8px;padding:10px 12px;font-size:13px;"
    "margin-bottom:16px}.ok{color:#0f7b4f}a.link{color:#1f564a;font-weight:600}"
    "code{background:#f1f1f1;padding:2px 6px;border-radius:5px;font-size:13px;word-break:break-all}"
)


def _page(title: str, inner: str) -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><title>{title}</title>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<style>{_CSS}</style></head><body><div class=wrap>{inner}</div></body></html>")


def _slug(url: str) -> str:
    bare = re.sub(r"^https?://", "", (url or "").lower()).strip("/")
    return re.sub(r"[^a-z0-9]+", "-", bare).strip("-")


def _validate_woo(store_url: str, ck: str, cs: str, probe=None) -> tuple[bool, str]:
    """One live read-only call to confirm the credentials work. `probe` is injectable."""
    try:
        if probe is None:
            from scoring.woocommerce_fetch import http_transport
            probe = http_transport(store_url, ck, cs)
        probe("orders", {"per_page": 1})
        return True, ""
    except Exception as exc:  # noqa: BLE001 — surface a short reason to the client
        return False, str(exc)[:180]


def _start_sync(shop: str) -> None:
    """Kick a background scoring sync for a tenant (idempotent)."""
    with _LOCK:
        if shop in _SYNCING:
            return
        _SYNCING.add(shop)

    def _run():
        try:
            data.sync_tenant(shop)
        except Exception:
            traceback.print_exc()  # stack only — never customer data
        finally:
            with _LOCK:
                _SYNCING.discard(shop)

    threading.Thread(target=_run, daemon=True).start()


def _connect_form(error: str = "", values: dict | None = None) -> str:
    v = values or {}
    code_field = ""
    if config.SIGNUP_CODE:
        code_field = ("<label>Signup code</label>"
                      "<input name=code type=password placeholder='from your Halia contact'>"
                      "<div class=help>Required to create an account.</div>")
    err = f"<div class=err>{html.escape(error)}</div>" if error else ""
    return _page("Connect your store — Halia", f"""
      <h1>Connect your store</h1>
      <p class=sub>Halia scores your customers for hidden VICs. Connect a read-only
      WooCommerce key — we never write to your store, and never store your customers.</p>
      <div class=card>{err}
      <form method=post action=/connect>
        <label>Store name</label>
        <input name=label placeholder='e.g. Glen Norah' value="{html.escape(v.get('label',''))}">
        <label>Store URL</label>
        <input name=store_url placeholder='https://yourstore.com' value="{html.escape(v.get('store_url',''))}">
        <label>WooCommerce consumer key</label>
        <input name=consumer_key placeholder='ck_…' value="{html.escape(v.get('consumer_key',''))}">
        <div class=help>WooCommerce → Settings → Advanced → REST API → Add key → permission <b>Read</b>.</div>
        <label>WooCommerce consumer secret</label>
        <input name=consumer_secret type=password placeholder='cs_…'>
        {code_field}
        <button class=btn type=submit>Connect &amp; score</button>
      </form></div>""")


def _hosted_head() -> str:
    # A refresh button for the hosted dashboard (re-pull + re-score), no App Bridge.
    return (
        "<style>#halia-refresh{position:fixed;top:14px;right:18px;z-index:200;padding:8px 14px;"
        "border-radius:8px;border:1px solid #d8c79a;background:#1f564a;color:#fff;"
        "font:600 13px system-ui;cursor:pointer}#halia-refresh[disabled]{opacity:.6}</style>"
        "<script>addEventListener('DOMContentLoaded',function(){var b=document.createElement('button');"
        "b.id='halia-refresh';b.textContent='\\u21bb Refresh scores';b.onclick=function(){"
        "b.disabled=true;b.textContent='Refreshing\\u2026';fetch('/app/refresh',{method:'POST'})"
        ".then(function(r){return r.json()}).then(function(){location.reload()})"
        ".catch(function(){b.textContent='Refresh failed';b.disabled=false})};"
        "document.body.appendChild(b)});</script>"
    )


def _preparing_page() -> HTMLResponse:
    inner = ("<h1>Scoring your store…</h1>"
             "<p class=sub>We're pulling your orders and scoring your customers. This can take "
             "a minute or two the first time — this page refreshes itself.</p>"
             "<div class=card><div style='display:flex;gap:10px;align-items:center'>"
             "<div class='spin' style='width:18px;height:18px;border:3px solid #d8d8d8;"
             "border-top-color:#1f564a;border-radius:50%;animation:s 1s linear infinite'></div>"
             "<span style='color:#616161;font-size:14px'>Working…</span></div></div>"
             "<style>@keyframes s{to{transform:rotate(360deg)}}</style>")
    resp = HTMLResponse(_page("Scoring… — Halia", inner))
    resp.headers["Refresh"] = "5"  # browser re-requests /app every 5s
    resp.headers["Cache-Control"] = "no-store"
    return resp


_WIZARD = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Connect your store · Halia</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f1ea;--ink:#13110c;--mute:#615b50;--faint:#9a9385;--gold:#7a7363;--line:rgba(20,18,12,.16);--serif:'Cormorant Garamond',Georgia,serif;--sans:'Inter',-apple-system,system-ui,sans-serif}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(1100px 600px at 50% -12%,#fcfaf5,#f4f1ea 62%);color:var(--ink);font-family:var(--sans);font-size:16px;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.bar{position:fixed;top:0;left:0;right:0;height:3px;background:rgba(20,18,12,.07);z-index:10}
.bar i{display:block;height:100%;width:0;background:var(--gold);transition:width .55s cubic-bezier(.2,.6,.2,1)}
.top{display:flex;justify-content:space-between;align-items:center;max-width:920px;margin:0 auto;padding:22px 28px}
.brand{font-family:var(--serif);font-size:24px;display:flex;align-items:center;gap:9px}.brand svg{width:20px;height:20px}
.stepn{font:500 12px var(--sans);letter-spacing:.16em;color:var(--faint)}
.stage{max-width:640px;margin:0 auto;padding:clamp(14px,4vh,46px) 28px 90px;position:relative}
.step{display:none}
.step.active{display:block;animation:in .55s cubic-bezier(.2,.6,.2,1)}
@keyframes in{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:none}}
.eyebrow{font:500 12px var(--sans);letter-spacing:.26em;text-transform:uppercase;color:var(--gold);margin-bottom:16px}
h1{font-family:var(--serif);font-weight:300;font-size:clamp(33px,5.4vw,50px);line-height:1.06;letter-spacing:-.01em;margin:0 0 16px}
h1 em{font-style:italic;color:var(--gold)}
.lede{font-size:18px;color:var(--mute);line-height:1.55;max-width:48ch;margin:0 0 26px}
label{display:block;font:600 13px var(--sans);margin:18px 0 7px}
.hint{font-size:13px;color:var(--mute);line-height:1.5;margin:6px 0 0}
input{width:100%;padding:14px 16px;border:1px solid var(--line);border-radius:11px;font:15px var(--sans);background:#fffdf8;color:var(--ink)}
input:focus{outline:none;border-color:var(--gold);box-shadow:0 0 0 3px rgba(122,115,99,.15)}
.row{display:flex;gap:18px;margin-top:32px;align-items:center}
.btn{display:inline-flex;align-items:center;gap:9px;font:600 15px var(--sans);padding:15px 30px;border-radius:999px;border:1px solid var(--ink);background:var(--ink);color:#f4f1ea;cursor:pointer;transition:.2s}
.btn:hover{background:#2a2620}.btn[disabled]{opacity:.45;cursor:default}
.back{font:600 14px var(--sans);color:var(--mute);background:none;border:none;cursor:pointer;padding:8px 4px}
.back:hover{color:var(--ink)}
.err{background:#fbeeec;border:1px solid #e0b4b0;color:#8e1f0b;border-radius:10px;padding:12px 14px;font-size:13.5px;margin:18px 0 0}
.cards{display:grid;gap:13px;margin-top:6px}
.pcard{display:flex;gap:16px;align-items:flex-start;border:1px solid var(--line);border-radius:14px;padding:19px 21px;cursor:pointer;background:#fffdf8;transition:.18s}
.pcard:hover{border-color:var(--gold)}
.pcard.sel{border-color:var(--ink);box-shadow:inset 0 0 0 1px var(--ink)}
.pcard .pi{font-family:var(--serif);font-size:21px;flex:none;width:42px;height:42px;border-radius:10px;background:#efeadd;display:flex;align-items:center;justify-content:center}
.pcard h3{font:600 16px var(--sans);margin:1px 0 4px}.pcard p{margin:0;font-size:13.5px;color:var(--mute);line-height:1.5}
.slist{margin:16px 0 4px;padding:0;list-style:none;counter-reset:s}
.slist li{position:relative;padding:8px 0 8px 36px;font-size:14.5px;color:var(--mute);line-height:1.5;counter-increment:s}
.slist li:before{content:counter(s);position:absolute;left:0;top:6px;width:23px;height:23px;border-radius:50%;background:var(--ink);color:#f4f1ea;font:600 12px var(--sans);display:flex;align-items:center;justify-content:center}
.slist b{color:var(--ink)}
.spin{width:22px;height:22px;border:3px solid rgba(20,18,12,.16);border-top-color:var(--gold);border-radius:50%;animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:560px){.grid2{grid-template-columns:1fr}}
details{margin-top:20px;border-top:1px solid var(--line)}
summary{cursor:pointer;font:600 13px var(--sans);color:var(--mute);padding:14px 0 4px;list-style:none}
summary::-webkit-details-marker{display:none}
</style></head><body>
<div class="bar"><i id="barfill"></i></div>
<header class="top"><a class="brand" href="/"><svg viewBox="0 0 24 24" fill="none"><path d="M12 2l2.6 6.4L21 11l-6.4 2.6L12 20l-2.6-6.4L3 11l6.4-2.6L12 2z" fill="#7a7363"/></svg>Halia</a><div class="stepn" id="stepn"></div></header>
<main class="stage" id="stage">

  <section class="step active" data-step="0">
    <div class="eyebrow">Welcome to Halia</div>
    <h1>Your best clients are <em>already here.</em></h1>
    <p class="lede">Hidden in your store is a small handful of people worth more than all the rest combined. In the next two minutes we will connect Halia and start bringing them into the light. Let us go and meet them.</p>
    <div class="row"><button class="btn" data-next>Let us begin <span>&rarr;</span></button></div>
  </section>

  <section class="step" data-step="1">
    <div class="eyebrow">Your store</div>
    <h1>First, your store.</h1>
    <p class="lede">Tell us who you are and where to find your shop. This is the store whose customers Halia will quietly read and grade.</p>
    <label>Store name</label>
    <input id="label" placeholder="e.g. Glen Norah" autocomplete="organization">
    <label>Store web address</label>
    <input id="store_url" placeholder="https://yourstore.com" inputmode="url" autocomplete="url">
    <div class="hint">The address your customers visit. Halia connects read-only and never changes a thing.</div>
    <div id="err1" class="err" style="display:none"></div>
    <div class="row"><button class="back" data-back>Back</button><button class="btn" data-next>Continue &rarr;</button></div>
  </section>

  <section class="step" data-step="2">
    <div class="eyebrow">Your store data</div>
    <h1>Connect your orders, <em>safely.</em></h1>
    <p class="lede">Halia reads your past orders to learn who your customers really are. You hand it a read-only key, so it can look but never touch.</p>
    <ol class="slist">
      <li>In your store admin, open <b>WooCommerce &rarr; Settings &rarr; Advanced &rarr; REST API</b>.</li>
      <li>Click <b>Add key</b>. Description: "Halia". Permissions: <b>Read</b>.</li>
      <li>Click <b>Generate API key</b>, then copy the two values it shows you.</li>
    </ol>
    <label>Consumer key</label>
    <input id="consumer_key" placeholder="ck_..." autocomplete="off">
    <label>Consumer secret</label>
    <input id="consumer_secret" type="password" placeholder="cs_..." autocomplete="off">
    <div id="codewrap" style="display:none">
      <label>Signup code</label>
      <input id="code" type="password" placeholder="from your Halia contact" autocomplete="off">
      <div class="hint">Required to create an account.</div>
    </div>
    <div id="err2" class="err" style="display:none"></div>
    <div class="row"><button class="back" data-back>Back</button><button class="btn" data-next>Continue &rarr;</button></div>
  </section>

  <section class="step" data-step="3">
    <div class="eyebrow">Your marketing platform</div>
    <h1>Where do you <em>email</em> from?</h1>
    <p class="lede">Once Halia finds your top clients, it sends them straight to the tool you already use, with their grade attached and ready to action. Which one is yours?</p>
    <div class="cards">
      <div class="pcard" data-plat="klaviyo"><div class="pi">K</div><div><h3>Klaviyo</h3><p>Push grades, build segments, and trigger flows for your hidden VICs.</p></div></div>
      <div class="pcard" data-plat="mailchimp"><div class="pi">M</div><div><h3>Mailchimp</h3><p>Tag and segment your audience by Halia grade, ready to send.</p></div></div>
      <div class="pcard" data-plat="later"><div class="pi">&middot;</div><div><h3>I will connect later</h3><p>Skip for now. You can connect either one any time from Settings.</p></div></div>
    </div>
    <div class="row"><button class="back" data-back>Back</button><button class="btn" data-next id="p3next" disabled>Continue &rarr;</button></div>
  </section>

  <section class="step" data-step="4">
    <div class="eyebrow" id="p4eye">Connect</div>
    <h1 id="p4title">Connect it.</h1>
    <p class="lede" id="p4lede"></p>
    <ol class="slist" id="p4steps"></ol>
    <label id="p4label">API key</label>
    <input id="api_key" placeholder="" autocomplete="off">
    <div class="hint" id="p4hint"></div>
    <div id="err4" class="err" style="display:none"></div>
    <div class="row"><button class="back" data-back>Back</button><button class="btn" data-next>Continue &rarr;</button></div>
  </section>

  <section class="step" data-step="5">
    <div class="eyebrow">Your top clients</div>
    <h1>What makes a client a <em>VIC?</em></h1>
    <p class="lede">Halia grades everyone, but you set the bar for a true top client. A good place to start is the yearly spend that already feels special to you. You can fine-tune this any time.</p>
    <label>A VIC spends at least, per year</label>
    <input id="vic_threshold" type="number" min="0" step="100" value="5000">
    <div class="hint">In your store's currency. Not sure? Leave it, the default works well.</div>
    <label>Sign your client notes as</label>
    <input id="sender_name" placeholder="e.g. Amara, or The Glen Norah team">
    <div class="hint">The name your clients see at the foot of a personal message.</div>
    <details>
      <summary>Add your own numbers for a sharper latent-value estimate (optional)</summary>
      <p class="hint" style="margin:12px 0 0">These help Halia estimate what a client could be worth if nurtured into a top client. Skip them and we use a sensible fallback.</p>
      <div class="grid2" style="margin-top:12px">
        <div><label style="margin-top:4px">Average order value</label><input id="aov" type="number" min="0" step="10" placeholder="optional"></div>
        <div><label style="margin-top:4px">Most orders from one client</label><input id="max_orders" type="number" min="0" step="1" placeholder="optional"></div>
      </div>
      <label>Your highest lifetime client value</label><input id="highest_lt" type="number" min="0" step="100" placeholder="optional">
    </details>
    <div class="row"><button class="back" data-back>Back</button><button class="btn" data-next id="finishbtn">Find my VICs &rarr;</button></div>
  </section>

  <section class="step" data-step="6">
    <div class="eyebrow">Almost there</div>
    <h1 id="donetitle">Scoring your store&hellip;</h1>
    <p class="lede" id="donelede">Halia is reading your orders and grading every customer. The first run takes a minute. Keep this tab open, your hidden VICs are on their way.</p>
    <div style="display:flex;gap:12px;align-items:center;margin-top:8px" id="spinrow"><div class="spin" id="spin"></div><span id="donesub" style="color:var(--mute);font-size:14px">Connecting&hellip;</span></div>
    <div id="err6" class="err" style="display:none"></div>
    <div class="row" id="donerow" style="display:none"><a class="btn" id="openbtn" href="#">Open my dashboard &rarr;</a></div>
  </section>

</main>
<script>
var SIGNUP=__SIGNUP_REQUIRED__;
var steps=[].slice.call(document.querySelectorAll('.step'));
var state={platform:null,cur:0};
if(SIGNUP) document.getElementById('codewrap').style.display='block';
function gv(id){var e=document.getElementById(id);return e?e.value.trim():'';}
function err(id,msg){var e=document.getElementById(id);if(e){e.textContent=msg;e.style.display='block';}}
function clearErrs(){['err1','err2','err4','err6'].forEach(function(i){var e=document.getElementById(i);if(e)e.style.display='none';});}
function order(){var o=[1,2,3];if(state.platform&&state.platform!=='later')o.push(4);o.push(5);return o;}
function show(n){
  state.cur=n;
  steps.forEach(function(s){s.classList.toggle('active',(+s.dataset.step)===n);});
  var fill=document.getElementById('barfill'),sn=document.getElementById('stepn'),o=order(),pos=o.indexOf(n);
  if(n===0){fill.style.width='6%';sn.textContent='';}
  else if(n===6){fill.style.width='100%';sn.textContent='';}
  else{fill.style.width=(((pos+1)/(o.length+1))*100)+'%';sn.textContent=(pos+1)+' of '+o.length;}
  window.scrollTo(0,0);
  if(n===4) fillPlatform();
}
function fillPlatform(){
  var k=state.platform==='klaviyo';
  document.getElementById('p4eye').textContent=k?'Connect Klaviyo':'Connect Mailchimp';
  document.getElementById('p4title').innerHTML=k?'Connect <em>Klaviyo.</em>':'Connect <em>Mailchimp.</em>';
  document.getElementById('p4lede').textContent=k
    ?'Create a private key so Halia can add grades to your profiles and build segments for you.'
    :'Grab an API key so Halia can tag your contacts by grade and build segments for you.';
  var s=k?['In Klaviyo, open <b>Settings &rarr; API keys</b>.','Click <b>Create Private API Key</b> and name it "Halia".','Give it <b>Full Access</b>, then copy the key.']
         :['In Mailchimp, click your profile, then <b>Account &amp; billing</b>.','Open <b>Extras &rarr; API keys</b>.','Click <b>Create A Key</b>, name it "Halia", then copy it.'];
  document.getElementById('p4steps').innerHTML=s.map(function(x){return '<li>'+x+'</li>';}).join('');
  document.getElementById('p4label').textContent=k?'Klaviyo private API key':'Mailchimp API key';
  var inp=document.getElementById('api_key');inp.placeholder=k?'pk_...':'xxxxxxxxxxxxxxxx-us21';
  document.getElementById('p4hint').textContent=k
    ?'It starts with pk_. We store it encrypted, and you can revoke it any time.'
    :'It ends in something like -us21. We store it encrypted, and you can revoke it any time.';
}
function valid(n){
  clearErrs();
  if(n===1){if(!/^https?:\/\//i.test(gv('store_url'))){err('err1','Enter your full store address, starting with https://');return false;}}
  if(n===2){if(!gv('consumer_key')||!gv('consumer_secret')){err('err2','Paste both your consumer key and secret.');return false;}
    if(SIGNUP&&!gv('code')){err('err2','Enter your signup code.');return false;}}
  if(n===4){var key=gv('api_key');if(!key){err('err4','Paste your '+(state.platform==='klaviyo'?'Klaviyo':'Mailchimp')+' key, or go back and choose to connect later.');return false;}
    if(state.platform==='klaviyo'&&key.indexOf('pk_')!==0){err('err4','A Klaviyo private key starts with pk_.');return false;}}
  return true;
}
function nextFrom(n){if(n===3)return(state.platform&&state.platform!=='later')?4:5;if(n===4)return 5;if(n===5)return 'finish';return n+1;}
function backFrom(n){if(n===5)return(state.platform&&state.platform!=='later')?4:3;if(n===4)return 3;return Math.max(0,n-1);}
function handleNext(){var n=state.cur;if(!valid(n))return;var t=nextFrom(n);if(t==='finish')finish();else show(t);}
[].forEach.call(document.querySelectorAll('[data-next]'),function(b){b.onclick=handleNext;});
[].forEach.call(document.querySelectorAll('[data-back]'),function(b){b.onclick=function(){show(backFrom(state.cur));};});
[].forEach.call(document.querySelectorAll('.pcard'),function(c){c.onclick=function(){
  [].forEach.call(document.querySelectorAll('.pcard'),function(x){x.classList.remove('sel');});
  c.classList.add('sel');state.platform=c.dataset.plat;document.getElementById('p3next').disabled=false;};});
document.getElementById('stage').addEventListener('keydown',function(e){
  if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();handleNext();}});
function payload(){return{
  label:gv('label'),store_url:gv('store_url'),consumer_key:gv('consumer_key'),consumer_secret:gv('consumer_secret'),code:gv('code'),
  platform:(!state.platform||state.platform==='later')?'':state.platform,api_key:gv('api_key'),
  vic_threshold:gv('vic_threshold'),sender_name:gv('sender_name'),aov:gv('aov'),max_orders:gv('max_orders'),highest_lt:gv('highest_lt')};}
function finish(){
  show(6);
  var sp=document.getElementById('spin');
  fetch('/v1/onboard',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload())})
   .then(function(r){return r.json().then(function(d){return{ok:r.ok,d:d};});})
   .then(function(res){
     if(!res.ok)throw new Error((res.d&&res.d.detail)||'Something went wrong.');
     var d=res.d;
     sp.style.display='none';
     document.getElementById('donetitle').innerHTML='Your store is <em>connected.</em>';
     document.getElementById('donelede').textContent=d.platform_warning?d.platform_warning:'Halia is scoring your customers right now. Your hidden VICs are moments away.';
     document.getElementById('donesub').textContent=d.platform_warning?'':'Done.';
     document.getElementById('openbtn').href=d.link;
     document.getElementById('donerow').style.display='flex';
     if(!d.platform_warning)setTimeout(function(){location.href=d.link;},1500);
   })
   .catch(function(e){
     var m=e.message||'Something went wrong.';
     if(/address|https/i.test(m)){show(1);err('err1',m);}
     else if(/woocommerce|key and secret|signup code/i.test(m)){show(2);err('err2',m);}
     else{sp.style.display='none';document.getElementById('donesub').textContent='We hit a snag.';err('err6',m);
       var o=document.getElementById('openbtn');o.textContent='Start over';o.href='/connect';document.getElementById('donerow').style.display='flex';}
   });
}
show(0);
</script>
</body></html>'''


def _connect_marketing(store, shop: str, platform: str, api_key: str) -> tuple[bool, str]:
    """Best-effort connect of a tenant's marketing platform during onboarding.

    Returns (connected, warning). Never raises: a platform hiccup must not block the
    store connection, which is the part that matters. They can finish in Settings.
    """
    platform, api_key = (platform or "").lower().strip(), (api_key or "").strip()
    if not platform or not api_key:
        return False, ""
    if platform == "klaviyo":
        if not api_key.startswith("pk_"):
            return False, ("That does not look like a Klaviyo private key (it should start with "
                           "pk_). You can add it in Settings whenever you like.")
        store.save_klaviyo(shop, api_key)
        try:
            from halia.adapters.klaviyo_segments import KlaviyoSegments
            KlaviyoSegments(api_key=api_key).ensure_defaults()
        except Exception:  # noqa: BLE001 — segments are a bonus, the key is saved
            traceback.print_exc()
        return True, ""
    if platform == "mailchimp":
        try:
            from halia.adapters.mailchimp_sink import (
                MailchimpSink, dc_from_key, list_audiences,
            )
            dc_from_key(api_key)
            audiences = list_audiences(api_key)
            if not audiences:
                return False, ("We connected, but found no Mailchimp audience. Create one in "
                               "Mailchimp, then connect from Settings.")
            a = audiences[0]
            MailchimpSink(api_key, a["id"]).ensure_merge_fields()
            store.save_mailchimp(shop, api_key, a["id"], a["name"])
            return True, ""
        except Exception as exc:  # noqa: BLE001
            return False, (f"We could not verify your Mailchimp key ({str(exc)[:120]}). "
                           "You can add it in Settings.")
    return False, ""


def register(app) -> None:
    """Mount the self-service onboarding + hosted dashboard routes."""

    @app.get("/connect", response_class=HTMLResponse)
    def connect_form():
        return HTMLResponse(_WIZARD.replace("__SIGNUP_REQUIRED__",
                                            "true" if config.SIGNUP_CODE else "false"))

    @app.post("/v1/onboard")
    def onboard(payload: dict = Body(...)) -> dict:
        p = payload or {}

        def g(k: str) -> str:
            return str(p.get(k, "") or "").strip()

        def num(k: str) -> float:
            try:
                return max(0.0, float(p.get(k) or 0))
            except (TypeError, ValueError):
                return 0.0

        if config.SIGNUP_CODE and g("code") != config.SIGNUP_CODE:
            raise HTTPException(403, "That signup code is not right. Check with your Halia contact.")

        store_url = g("store_url").rstrip("/")
        shop = _slug(store_url)
        if not shop or not store_url.startswith("http"):
            raise HTTPException(400, "Enter your full store web address, starting with https://")
        ck, cs = g("consumer_key"), g("consumer_secret")
        if not ck or not cs:
            raise HTTPException(400, "Add your WooCommerce consumer key and secret.")

        ok, why = _validate_woo(store_url, ck, cs)
        if not ok:
            raise HTTPException(400, f"We could not reach WooCommerce with those keys: {why}")

        import json as _json

        token = new_token()
        store = shop_store()
        label = g("label") or shop
        store.create_tenant(shop, "woocommerce", label, hash_token(token))
        store.save_woocommerce(shop, store_url, ck, cs)
        store.save_settings(shop, _json.dumps({
            "vic_threshold": num("vic_threshold") or 5000,
            "sender_name": g("sender_name")[:120],
            "aov": num("aov"), "max_orders": int(num("max_orders")), "highest_lt": num("highest_lt"),
        }))

        connected, warning = _connect_marketing(store, shop, g("platform"), g("api_key"))
        _start_sync(shop)  # warm the cache while they read the closing screen
        return {"ok": True, "link": f"/app?t={token}", "label": label,
                "platform_connected": connected, "platform_warning": warning}

    @app.post("/connect", response_class=HTMLResponse)
    def connect_submit(
        store_url: str = Form(...),
        consumer_key: str = Form(...),
        consumer_secret: str = Form(...),
        label: str = Form(""),
        code: str = Form(""),
    ):
        values = {"store_url": store_url, "consumer_key": consumer_key, "label": label}
        if config.SIGNUP_CODE and code.strip() != config.SIGNUP_CODE:
            return HTMLResponse(_connect_form("Wrong signup code.", values), status_code=403)

        store_url = store_url.strip().rstrip("/")
        shop = _slug(store_url)
        if not shop or not store_url.startswith("http"):
            return HTMLResponse(_connect_form("Enter a full store URL (https://…).", values), 400)

        ok, why = _validate_woo(store_url, consumer_key.strip(), consumer_secret.strip())
        if not ok:
            return HTMLResponse(_connect_form(
                f"Couldn't reach WooCommerce with those keys: {why}", values), 400)

        token = new_token()
        store = shop_store()
        store.create_tenant(shop, "woocommerce", label.strip() or shop, hash_token(token))
        store.save_woocommerce(shop, store_url, consumer_key.strip(), consumer_secret.strip())
        _start_sync(shop)  # warm the cache while they read the success page

        link = f"/app?t={token}"
        inner = (f"<h1 class=ok>✓ {html.escape(label.strip() or shop)} connected</h1>"
                 "<p class=sub>Your private dashboard is ready. Bookmark this link — it's the "
                 "only way in, so keep it safe.</p>"
                 f"<div class=card><p style='margin:0 0 14px'><a class=link href='{link}'>"
                 "Open my dashboard →</a></p>"
                 f"<div class=help>Private link</div><code>{html.escape(link)}</code></div>")
        return HTMLResponse(_page("Connected — Halia", inner))

    @app.get("/app", response_class=HTMLResponse)
    def hosted_dashboard(request: Request):
        from build_mvp import render_payload

        # First arrival carries ?t=<token>: set the cookie and redirect to a clean URL.
        if request.query_params.get("t"):
            shop = resolve_tenant(request)
            if not shop:
                return HTMLResponse(_page("Halia", "<h1>Invalid link</h1><p class=sub>This access "
                                          "link isn't valid. Ask your Halia contact for a new one.</p>"), 401)
            resp = RedirectResponse("/app", status_code=303)
            resp.set_cookie(COOKIE, request.query_params["t"], httponly=True,
                            secure=request.url.scheme == "https", samesite="lax",
                            max_age=60 * 60 * 24 * 365)
            return resp

        shop = require_tenant(request)
        entry = cache.get(shop)
        if entry is None:
            _start_sync(shop)
            return _preparing_page()
        try:
            body = render_payload(entry["payload"], head_extra=_hosted_head())
        except Exception:
            traceback.print_exc()
            return HTMLResponse(_page("Halia", "<h1>Couldn't load your scores</h1>"
                                      "<p class=sub>Hit refresh in a moment.</p>"), 500)
        resp = HTMLResponse(body)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/app/refresh")
    def hosted_refresh(request: Request):
        shop = require_tenant(request)
        cache.evict(shop)
        entry = data.sync_tenant(shop)
        return {"shop": shop, "hidden_vics": len(data.hidden_results(entry)) if entry else 0}
