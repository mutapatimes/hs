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

import hashlib
import hmac
import html
import re
import secrets
import threading
import time
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

# The version of the Terms/Privacy a client accepts at onboarding (recorded for the audit
# trail). Bump when the legal terms change materially.
TERMS_VERSION = "2026-06-30"

# Pending WooCommerce one-click authorisations: token -> {store_url, ck, cs, ts}. The merchant's
# browser holds the token; WooCommerce posts the read-only keys to our callback, which we match by
# token. In RAM only, short-lived; never customer data.
_PENDING_WOO: dict[str, dict] = {}
_WOO_LOCK = threading.Lock()
_WOO_TTL = 1800  # 30 minutes


def _woo_prune() -> None:
    cutoff = time.time() - _WOO_TTL
    for k in [k for k, v in _PENDING_WOO.items() if v["ts"] < cutoff]:
        _PENDING_WOO.pop(k, None)


def _woo_pending_new(store_url: str) -> str:
    tok = secrets.token_urlsafe(24)
    with _WOO_LOCK:
        _woo_prune()
        _PENDING_WOO[tok] = {"store_url": store_url, "ck": None, "cs": None, "ts": time.time()}
    return tok


def _woo_pending_set(tok: str, ck: str, cs: str) -> None:
    with _WOO_LOCK:
        p = _PENDING_WOO.get(tok)
        if p:
            p["ck"], p["cs"] = ck, cs


def _woo_pending_get(tok: str) -> dict | None:
    with _WOO_LOCK:
        _woo_prune()
        p = _PENDING_WOO.get(tok)
        return dict(p) if p else None


def _woo_pending_pop(tok: str) -> None:
    with _WOO_LOCK:
        _PENDING_WOO.pop(tok, None)


# Pending Shopify OAuth installs: state-token -> {shop_domain, token, ts}. Same idea as Woo: the
# merchant approves in Shopify, our callback exchanges the code for an access token and stores it
# here keyed by the OAuth `state`, and the wizard polls until ready. RAM only, short-lived.
_PENDING_SHOP: dict[str, dict] = {}
_SHOP_LOCK = threading.Lock()


def _shop_prune() -> None:
    cutoff = time.time() - _WOO_TTL
    for k in [k for k, v in _PENDING_SHOP.items() if v["ts"] < cutoff]:
        _PENDING_SHOP.pop(k, None)


def _shop_pending_new(shop_domain: str) -> str:
    tok = secrets.token_urlsafe(24)
    with _SHOP_LOCK:
        _shop_prune()
        _PENDING_SHOP[tok] = {"shop_domain": shop_domain, "token": None, "ts": time.time()}
    return tok


def _shop_pending_set(tok: str, token: str, shop_domain: str | None = None) -> None:
    with _SHOP_LOCK:
        p = _PENDING_SHOP.get(tok)
        if p:
            p["token"] = token
            if shop_domain:
                p["shop_domain"] = shop_domain


def _shop_pending_get(tok: str) -> dict | None:
    with _SHOP_LOCK:
        _shop_prune()
        p = _PENDING_SHOP.get(tok)
        return dict(p) if p else None


def _shop_pending_pop(tok: str) -> None:
    with _SHOP_LOCK:
        _PENDING_SHOP.pop(tok, None)


def _verify_shopify_hmac(params: dict, secret: str) -> bool:
    """Verify the HMAC on a Shopify OAuth callback (sorted params, excluding hmac/signature)."""
    if not secret:
        return False
    sig = params.get("hmac", "")
    items = {k: v for k, v in params.items() if k not in ("hmac", "signature")}
    msg = "&".join(f"{k}={items[k]}" for k in sorted(items))
    digest = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)


def _shopify_exchange(shop_domain: str, code: str, post=None) -> str:
    """Exchange an OAuth code for a permanent Admin API access token. `post` is injectable."""
    body = {"client_id": config.SHOPIFY_API_KEY, "client_secret": config.SHOPIFY_API_SECRET,
            "code": code}
    if post is None:
        import requests
        r = requests.post(f"https://{shop_domain}/admin/oauth/access_token", json=body, timeout=20)
        r.raise_for_status()
        data = r.json()
    else:
        data = post(shop_domain, body)
    token = (data or {}).get("access_token")
    if not token:
        raise RuntimeError("Shopify did not return an access token")
    return token

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
    except Exception as exc:  # noqa: BLE001 - surface a short reason to the client
        return False, str(exc)[:180]


# Background-sync status per shop, so the preparing page can reassure / show errors rather than
# spin forever. Plus a "ready email sent" guard so we email a tenant only once.
_SYNC_STATUS: dict[str, dict] = {}
_NOTIFIED: set[str] = set()


def _set_status(shop: str, state: str, error: str = "") -> None:
    with _LOCK:
        _SYNC_STATUS[shop] = {"state": state, "error": error, "ts": time.time()}


def sync_status(shop: str) -> dict:
    with _LOCK:
        return dict(_SYNC_STATUS.get(shop) or {"state": "idle", "error": "", "ts": 0})


def _send_ready_email(shop: str, entry: dict | None) -> None:
    """Email the merchant that their scores are ready (best-effort; no-op without email config)."""
    try:
        from halia import notify as _notify
        from halia.api.settings import settings_for

        if not _notify.email_configured():
            return
        s = settings_for(shop)
        recipients = s.get("notify_emails") or ([s["account_email"]] if s.get("account_email") else [])
        if not recipients:
            return
        base = (config.HALIA_APP_URL or "").rstrip("/")
        count = len(data.hidden_results(entry)) if entry else 0
        html = (f"<p>Good news, your store has finished scoring.</p>"
                f"<p>Halia found <b>{count}</b> hidden VICs in your customers. Open your dashboard "
                f"to see them, ranked and ready to act on:</p>"
                f"<p><a href='{base}/app'>{base}/app</a></p>"
                f"<p style='color:#888;font-size:13px'>Open it on the device you set Halia up on, "
                f"so you go straight in.</p>")
        for em in recipients:
            _notify.send_email(em, "Your hidden VICs are ready · Halia", html)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def _start_sync(shop: str, notify: bool = False) -> None:
    """Kick a background scoring sync for a tenant (idempotent). On completion, optionally email."""
    with _LOCK:
        if shop in _SYNCING:
            return
        st = _SYNC_STATUS.get(shop)
        if st and st["state"] == "error" and time.time() - st["ts"] < 60:
            return  # brief back-off after a failure, so a refresh loop can't hammer the store
        _SYNCING.add(shop)
    _set_status(shop, "running")

    def _run():
        try:
            entry = data.sync_tenant(shop)
            _set_status(shop, "done")
            if notify and shop not in _NOTIFIED:
                _NOTIFIED.add(shop)
                _send_ready_email(shop, entry)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()  # stack only - never customer data
            _set_status(shop, "error", str(exc)[:200])
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
    return _page("Connect your store - Halia", f"""
      <h1>Connect your store</h1>
      <p class=sub>Halia scores your customers for hidden VICs. Connect a read-only
      WooCommerce key - we never write to your store, and never store your customers.</p>
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


_PREPARING = r'''<!doctype html><html lang="en"><head><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%237a7363'>&#8258;</text></svg>"><meta charset="utf-8">
<title>Scoring your store · Halia</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<noscript><meta http-equiv="refresh" content="5"></noscript>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f1ea;--ink:#13110c;--mute:#615b50;--faint:#9a9385;--gold:#7a7363;--serif:'Cormorant Garamond',Georgia,serif;--sans:'Inter',-apple-system,system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(1100px 600px at 50% -12%,#fcfaf5,#f4f1ea 62%);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}
.top{max-width:960px;margin:0 auto;padding:22px 28px}
.brand{font-family:var(--serif);font-size:24px;display:flex;align-items:center;gap:9px}.brand svg{width:20px;height:20px}
.stage{max-width:640px;margin:0 auto;padding:clamp(40px,12vh,120px) 28px;text-align:center}
.eyebrow{font:500 12px var(--sans);letter-spacing:.26em;text-transform:uppercase;color:var(--gold);margin-bottom:18px}
h1{font-family:var(--serif);font-weight:300;font-size:clamp(34px,6vw,56px);line-height:1.06;letter-spacing:-.01em;margin:0 0 18px}
h1 em{font-style:italic;color:var(--gold)}
.lede{font-size:18px;color:var(--mute);line-height:1.5;min-height:3em;transition:opacity .25s;margin:0 auto;max-width:42ch}
.lede b{color:var(--ink);font-weight:600}
.track{height:6px;background:rgba(20,18,12,.1);border-radius:99px;overflow:hidden;max-width:420px;margin:30px auto 0;position:relative}
.track i{display:block;height:100%;width:8%;background:linear-gradient(90deg,#7a7363,#b7ad99);border-radius:99px;transition:width 1.1s cubic-bezier(.3,.7,.3,1)}
.track:after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.55),transparent);transform:translateX(-100%);animation:sh 1.8s infinite}
@keyframes sh{to{transform:translateX(100%)}}
.fine{font-size:13px;color:var(--faint);margin:22px 0 0}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--gold);margin-right:8px;vertical-align:middle;animation:pl 1.1s infinite}
@keyframes pl{0%,100%{opacity:.3}50%{opacity:1}}
.term{max-width:520px;margin:34px auto 0;background:#0e1012;border:1px solid rgba(20,18,12,.18);border-radius:12px;overflow:hidden;text-align:left;box-shadow:0 34px 70px -34px rgba(0,0,0,.45)}
.term .bar{display:flex;align-items:center;gap:7px;padding:11px 14px;background:#17191c;border-bottom:1px solid rgba(255,255,255,.06)}
.term .bar i{width:11px;height:11px;border-radius:50%;background:#3a3d40}
.term .bar i:nth-child(1){background:#ff5f57}.term .bar i:nth-child(2){background:#febc2e}.term .bar i:nth-child(3){background:#28c840}
.term .bar span{margin-left:8px;color:#7d8186;font:500 12px var(--sans)}
.term .body{padding:14px 16px;height:176px;overflow:hidden;font:12.5px/1.72 ui-monospace,SFMono-Regular,Menlo,monospace}
.term .ln{white-space:pre-wrap;color:#c9cdd2;animation:tin .25s ease}
@keyframes tin{from{opacity:0}to{opacity:1}}
.term .ln.ok{color:#5bd6a0}.term .ln.dim{color:#7d8186}.term .ln.calc{color:#8fb6e0}
.term .pr{color:#5bd6a0}.term .cmd{color:#eaeef2}.term .br{color:#d8b96a}
.term .caret{display:inline-block;width:8px;height:14px;background:#5bd6a0;vertical-align:-2px;animation:bk 1s step-end infinite}
@keyframes bk{50%{opacity:0}}
</style></head><body>
<header class="top"><a class="brand" href="/"><span aria-hidden="true" style="font-family:'Cormorant Garamond',Georgia,serif;font-size:22px;line-height:1;color:#7a7363">&#8258;</span>Halia</a></header>
<main class="stage">
  <div class="eyebrow" id="phase"><span class="dot"></span>Scoring your store</div>
  <h1 id="head">Finding your <em>hidden VICs</em></h1>
  <p class="lede" id="msg">Reading every order in your store...</p>
  <div class="track"><i id="bar"></i></div>
  <div class="term">
    <div class="bar"><i></i><i></i><i></i><span>halia &middot; scoring engine</span></div>
    <div class="body"><div id="termlines"></div><div class="ln"><span class="pr">$</span> <span class="caret"></span></div></div>
  </div>
  <p class="fine" id="leave">__LEAVE__</p>
</main>
<script>
var MSGS=[
 "Reading every order in your store...",
 "Matching customers to the signals behind them...",
 "Spotting the quiet big spenders...",
 "Weighing wealth and intent signals together...",
 "Separating your hidden VICs from the crowd...",
 "Estimating the revenue waiting in your list...",
 "Ranking your clients by what they could be worth...",
 "Finding the few worth more than all the rest...",
 "This is the exciting part..."
];
var msg=document.getElementById('msg'),bar=document.getElementById('bar'),mi=0,prog=8;
var cyc=setInterval(function(){mi=(mi+1)%MSGS.length;msg.style.opacity=0;setTimeout(function(){msg.textContent=MSGS[mi];msg.style.opacity=1;},250);},2600);
var creep=setInterval(function(){prog=Math.min(92,prog+Math.random()*7+1.5);bar.style.width=prog+'%';},1300);
setTimeout(function(){bar.style.width='12%';},80);
var SCRIPT=[
 {p:'halia engine --version'},
 {d:'Halia scoring engine v2.4.1   zero-retention'},
 {p:'halia connect --read-only'},
 {o:'✓ secure link established (read-only, never writes)'},
 {bar:'pulling recent orders', ms:1900, done:'→ 4,213 orders loaded into memory'},
 {c:'aggregating orders  ->  1,884 unique customers'},
 {p:'halia signals --load'},
 {spin:'loading HNWI postcode index', ms:1500, done:'✓ 41,309 high-value postcodes'},
 {spin:'loading premium domains + wealth-office lists', ms:1500, done:'✓ 12,740 domains · 2,118 firms'},
 {spin:'loading stylist + rich-list directories', ms:1400, done:'✓ stylists 3,025 · rich-list 4,118'},
 {spin:'loading delivery-venue gazetteer', ms:1300, done:'✓ FBOs 318 · marinas 642 · hotels 1,907'},
 {o:'✓ 31 signals registered by Halia'},
 {p:'halia score --calibrate'},
 {c:'weights  work_email·3 hnwi_postcode·3 delivery_venue·3 premium_card·3'},
 {c:'         honorific·2 wealth_office·2 fashion_stylist·2 company_keyword·2'},
 {c:'         post_nominal·2 elite_alumni·2 assistant_order·2  +19 supporting'},
 {c:'venue overrides  private_jet_fbo·5  marina·5    domain:elite·3'},
 {spin:'evaluating 31 signals per customer', ms:2300, done:'✓ signals evaluated for 1,884 customers'},
 {c:'cust#4821  work_email(3) hnwi_postcode(3) honorific(2)   Sw = 8'},
 {spin:'normalizing + weighting', ms:1700, done:'normalize -> 0.71  ->  calibrate -> 84.6  ->  grade A'},
 {c:'cust#1190  delivery_venue:marina(5) premium_card(3)   Sw = 8  ->  A*'},
 {c:'cust#3307  styling_service(3) company_keyword(2)   trade-account flag'},
 {c:'cust#0925  post_nominal(2) elite_alumni(2) premium_email(2)   Sw = 6  ->  B'},
 {spin:'applying supporting-signal rules', ms:1500, done:'✓ never flagged on a sole weak tell'},
 {c:'hidden-VIC rule:  >=1 strong signal AND spend < threshold £5,000'},
 {c:'cust#4821  spend £1,240  <  £5,000   ->  hidden VIC ✓'},
 {c:'cohort  AOV £420 · max-orders 14 · ceiling £18,400'},
 {spin:'estimating latent value', ms:2000, done:'latent = spend + (ceiling - spend)·score = £14,800'},
 {bar:'scoring all customers', ms:2500, done:'✓ 1,884 customers graded  A* -> C'},
 {spin:'ranking by percentile', ms:1700, done:'★ cust#4821 in top 3.2%   signals fired = 7'},
 {c:'grade thresholds  A* >=90   A >=80   B >=65   C <65'},
 {p:'halia surface --hidden-vics'},
 {o:'✓ 87 hidden VICs surfaced and ranked by Halia'},
 {spin:'preparing your dashboard', ms:1300, done:'✓ Halia ready'}
];
var termlines=document.getElementById('termlines'),termTick,termStop=false;
var SPIN=['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏'];
function cap(){while(termlines.children.length>6)termlines.removeChild(termlines.firstChild);}
function el(cls){var d=document.createElement('div');d.className='ln'+(cls?' '+cls:'');termlines.appendChild(d);cap();return d;}
function doneCls(t){return (t&&t.charAt(0)==='✓')?'ln ok':'ln calc';}
function addStatic(s){
  var d=el(s.o?'ok':(s.c?'calc':'dim'));
  if(s.p){d.innerHTML='<span class="pr">$</span> <span class="cmd">'+s.p+'</span>';}
  else{d.textContent=s.o||s.c||s.d;}
}
function spinStep(s,cb){
  var d=el('dim'),fi=0;
  var iv=setInterval(function(){if(termStop){clearInterval(iv);return;}d.textContent=SPIN[fi++%SPIN.length]+'  '+s.spin;},80);
  termTick=setTimeout(function(){clearInterval(iv);d.className=doneCls(s.done);d.textContent=s.done;cb();},s.ms||1500);
}
function barStep(s,cb){
  var d=el('dim'),p=0,W=10;
  var iv=setInterval(function(){if(termStop){clearInterval(iv);return;}p=Math.min(100,p+Math.random()*15+6);var f=Math.round(p/100*W);d.innerHTML='<span class="br">['+Array(f+1).join('█')+Array(W-f+1).join('░')+']</span> '+Math.round(p)+'%  '+s.bar;},170);
  termTick=setTimeout(function(){clearInterval(iv);d.className=doneCls(s.done);d.textContent=s.done;cb();},s.ms||2000);
}
function next(i,delay){if(termStop)return;termTick=setTimeout(function(){run(i+1);},delay);}
function run(i){
  if(termStop)return;
  var s=SCRIPT[i%SCRIPT.length];
  if(s.spin){spinStep(s,function(){next(i,500);});}
  else if(s.bar){barStep(s,function(){next(i,500);});}
  else{addStatic(s);next(i,s.p?650:(s.c?550:900));}
}
if(termlines)run(0);
function done(d){
  clearInterval(cyc);clearInterval(creep);termStop=true;clearTimeout(termTick);bar.style.width='100%';
  document.getElementById('phase').innerHTML='Ready';
  document.getElementById('head').innerHTML='Your VICs are <em>ready.</em>';
  var c=(d&&d.count)||'0',l=(d&&d.latent)||'';
  msg.style.opacity=0;
  setTimeout(function(){msg.innerHTML=l?('We found <b>'+c+'</b> hidden VICs worth about <b>'+l+'</b>.'):('We found <b>'+c+'</b> hidden VICs.');msg.style.opacity=1;},250);
  document.getElementById('leave').textContent='Opening your dashboard...';
  setTimeout(function(){location.href='/app';},1700);
}
function poll(){
  fetch('/app/status',{headers:{accept:'application/json'}}).then(function(r){return r.json();})
   .then(function(d){if(d&&d.state==='done'){done(d);}else{setTimeout(poll,2000);}})
   .catch(function(){setTimeout(poll,3000);});
}
setTimeout(poll,1500);
</script>
</body></html>'''


def _preparing_page(shop: str | None = None) -> HTMLResponse:
    from halia import notify as _notify

    leave = ("You can close this tab. We will email you the moment your VICs are ready."
             if _notify.email_configured() else
             "Keep this tab open. It opens your dashboard automatically the second it is ready.")
    resp = HTMLResponse(_PREPARING.replace("__LEAVE__", leave))
    resp.headers["Cache-Control"] = "no-store"
    return resp


_TEASER = r'''<!doctype html><html lang="en"><head><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%237a7363'>&#8258;</text></svg>"><meta charset="utf-8">
<title>Your hidden VICs · Halia</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f1ea;--ink:#13110c;--mute:#615b50;--faint:#9a9385;--gold:#7a7363;--line:rgba(20,18,12,.16);--serif:'Cormorant Garamond',Georgia,serif;--sans:'Inter',-apple-system,system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(1100px 600px at 50% -12%,#fcfaf5,#f4f1ea 62%);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.top{max-width:960px;margin:0 auto;padding:22px 28px}
.brand{font-family:var(--serif);font-size:24px;display:flex;align-items:center;gap:9px}.brand svg{width:20px;height:20px}
.stage{max-width:680px;margin:0 auto;padding:clamp(20px,6vh,70px) 28px 90px;text-align:center}
.eyebrow{font:500 12px var(--sans);letter-spacing:.26em;text-transform:uppercase;color:var(--gold);margin-bottom:18px}
h1{font-family:var(--serif);font-weight:300;font-size:clamp(34px,6vw,58px);line-height:1.05;letter-spacing:-.01em;margin:0 0 18px}
h1 em{font-style:italic;color:var(--gold)}
.lede{font-size:18px;color:var(--mute);line-height:1.55;max-width:54ch;margin:0 auto 30px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:34px 0 30px}
@media(max-width:560px){.stats{grid-template-columns:1fr}}
.stat{border:1px solid var(--line);border-radius:14px;padding:22px 16px;background:#fffdf8}
.stat .num{font-family:var(--serif);font-weight:400;font-size:clamp(28px,5vw,44px);line-height:1;color:var(--ink)}
.stat .lab{font:500 12px var(--sans);letter-spacing:.06em;color:var(--mute);margin-top:10px;text-transform:uppercase}
.btn{display:inline-flex;align-items:center;gap:9px;font:600 16px var(--sans);padding:17px 36px;border-radius:999px;border:1px solid var(--ink);background:var(--ink);color:#f4f1ea;cursor:pointer;transition:.2s}
.btn:hover{background:#2a2620}.btn[disabled]{opacity:.55;cursor:default}
.fine{font-size:13px;color:var(--faint);margin:18px 0 0}
.err{background:#fbeeec;border:1px solid #e0b4b0;color:#8e1f0b;border-radius:10px;padding:12px 14px;font-size:13.5px;margin:18px auto 0;max-width:42ch}
</style></head><body>
<header class="top"><a class="brand" href="/"><span aria-hidden="true" style="font-family:'Cormorant Garamond',Georgia,serif;font-size:22px;line-height:1;color:#7a7363">&#8258;</span>Halia</a></header>
<main class="stage">
  <div class="eyebrow">__LABEL__ &middot; the result is in</div>
  <h1>You have <em>__COUNT__</em> hidden VICs,<br>worth an estimated <em>__LATENT__</em>.</h1>
  <p class="lede">Halia read your store and found high-value clients you are not treating like VIPs yet, and estimated the revenue waiting inside them. Their names, scores, the signals behind each one, and one-tap outreach are a single step away.</p>
  <div class="stats">
    <div class="stat"><div class="num">__COUNT__</div><div class="lab">Hidden VICs found</div></div>
    <div class="stat"><div class="num">__LATENT__</div><div class="lab">Latent value to unlock</div></div>
    <div class="stat"><div class="num">__TOPTIER__</div><div class="lab">Graded A or above</div></div>
  </div>
  <button class="btn" id="unlock">Unlock this hidden revenue now &rarr;</button>
  <p class="fine">Cancel anytime. Halia stays zero-retention: your customers are scored in the moment and never stored.</p>
  <div class="err" id="err" style="display:none"></div>
</main>
<script>
document.getElementById('unlock').onclick=function(){
  var b=this;b.disabled=true;b.textContent='Opening secure checkout…';
  fetch('/v1/checkout',{method:'POST'}).then(function(r){return r.json();})
   .then(function(d){if(d&&d.url){location.href=d.url;}else{throw new Error('no url');}})
   .catch(function(){b.disabled=false;b.innerHTML='Unlock this hidden revenue now &rarr;';
     var e=document.getElementById('err');e.textContent='We could not start checkout just now. Please try again.';e.style.display='block';});
};
</script>
</body></html>'''


def _teaser_page(label: str, count: str, latent: str, toptier: str) -> str:
    return (_TEASER.replace("__LABEL__", html.escape(str(label)))
            .replace("__COUNT__", html.escape(str(count)))
            .replace("__LATENT__", html.escape(str(latent)) or "your hidden value")
            .replace("__TOPTIER__", html.escape(str(toptier))))


def _norm_shop(value: str) -> str:
    """Normalise a Shopify shop to its myshopify domain (accepts a handle, domain, or URL)."""
    s = re.sub(r"^https?://", "", (value or "").lower()).strip().strip("/").split("/")[0]
    if not s:
        return ""
    return s if s.endswith(".myshopify.com") else f"{s}.myshopify.com"


def _validate_shopify(shop_domain: str, token: str, probe=None) -> tuple[bool, str]:
    """One live Admin API call to confirm a Shopify custom-app token works. `probe` is injectable."""
    try:
        if probe is None:
            from scoring.shopify_fetch import http_transport
            probe = http_transport(shop_domain, token)
        res = probe("{ shop { name } }", {})
        if isinstance(res, dict) and res.get("errors"):
            import json
            return False, json.dumps(res["errors"])[:160]
        return True, ""
    except Exception as exc:  # noqa: BLE001 - surface a short reason
        return False, str(exc)[:180]


_SHOPIFY_HINTS = ("cdn.shopify.com", "/cdn/shop/", "shopify.shop", "x-shopify", "x-shopid",
                  "myshopify.com", "shopify-section", "shopify.theme")
_WOO_HINTS = ("woocommerce", "/plugins/woocommerce", "wp-json/wc/", "wc-block", "wc_add_to_cart",
              "woocommerce-page")


def _detect_platform(store_url: str, fetch=None) -> dict:
    """Best-effort: fetch the storefront once and guess Shopify vs WooCommerce.

    Returns {"platform": "shopify"|"woocommerce"|"unknown", "myshopify": domain-or-empty}.
    Never raises; an unknown result simply lets the wizard ask the merchant to choose.
    """
    url = (store_url or "").strip()
    if not url:
        return {"platform": "unknown", "myshopify": ""}
    if not url.startswith("http"):
        url = "https://" + url
    try:
        if fetch is None:
            import requests
            r = requests.get(url, timeout=7, allow_redirects=True,
                             headers={"User-Agent": "HaliaBot/1.0 (+store detection)"})
            header_blob = " ".join(f"{k}:{v}" for k, v in r.headers.items())
            body = r.text[:200000]
        else:
            header_blob, body = fetch(url)
    except Exception:  # noqa: BLE001 - detection is a convenience, never fatal
        return {"platform": "unknown", "myshopify": ""}
    blob = (header_blob + " " + (body or "")).lower()
    m = re.search(r"([a-z0-9][a-z0-9\-]*\.myshopify\.com)", blob)
    myshop = m.group(1) if m else ""
    shopify = any(h in blob for h in _SHOPIFY_HINTS)
    woo = any(h in blob for h in _WOO_HINTS)
    if shopify and not woo:
        platform = "shopify"
    elif woo and not shopify:
        platform = "woocommerce"
    elif shopify and woo:
        platform = "shopify"
    else:
        platform = "unknown"
    return {"platform": platform, "myshopify": myshop}


_WIZARD = r'''<!doctype html><html lang="en"><head><link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%237a7363'>&#8258;</text></svg>"><meta charset="utf-8">
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
.termsrow{display:flex;gap:10px;align-items:flex-start;font:400 13.5px var(--sans);color:var(--mute);margin:22px 0 0;cursor:pointer}
.termsrow input{width:auto;flex:none;margin:2px 0 0;padding:0;cursor:pointer}
.termsrow a{color:var(--gold);text-decoration:underline}
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
.emrow{display:flex;gap:8px;margin-top:8px;align-items:center}
.emrow input{flex:1}
.emrow .rm{flex:none;width:40px;height:40px;border:1px solid var(--line);border-radius:10px;background:#fffdf8;color:var(--mute);cursor:pointer;font-size:18px;line-height:1}
.emrow .rm:hover{color:var(--ink);border-color:var(--ink)}
.addmail{margin-top:12px;background:none;border:none;color:var(--gold);font:600 14px var(--sans);cursor:pointer;padding:6px 0}
.addmail:hover{color:var(--ink)}
</style></head><body>
<div class="bar"><i id="barfill"></i></div>
<header class="top"><a class="brand" href="/"><span aria-hidden="true" style="font-family:'Cormorant Garamond',Georgia,serif;font-size:22px;line-height:1;color:#7a7363">&#8258;</span>Halia</a><div class="stepn" id="stepn"></div></header>
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
    <div class="eyebrow" id="srceye">Your store data</div>
    <h1 id="srctitle">Connect your orders, <em>safely.</em></h1>
    <p class="lede" id="srclede">Halia reads your past orders to learn who your customers really are. It connects read-only, so it can look but never touch.</p>
    <div id="srcbody"></div>
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
    <div class="row"><button class="back" data-back>Back</button><button class="btn" data-next>Continue &rarr;</button></div>
  </section>

  <section class="step" data-step="6">
    <div class="eyebrow">Stay in the loop</div>
    <h1>Never miss a <em>big moment.</em></h1>
    <p class="lede">When a top client places an order, in person at the till or online, Halia can alert your team in real time so you can look after them right away. Where should those alerts go?</p>
    <label>Your email</label>
    <input id="email" type="email" placeholder="you@yourstore.com" autocomplete="email">
    <div class="hint">For your account and important notices. You will receive alerts here too.</div>
    <label>Also send order alerts to</label>
    <div id="emaillist"></div>
    <button type="button" class="addmail" id="addmail">+ Add another recipient</button>
    <label class="termsrow"><input type="checkbox" id="accept_terms"><span>I have read and agree to Halia's <a href="/terms" target="_blank" rel="noopener">Terms of Service</a> and <a href="/privacy" target="_blank" rel="noopener">Privacy Policy</a>.</span></label>
    <div id="err6" class="err" style="display:none"></div>
    <div class="row"><button class="back" data-back>Back</button><button class="btn" data-next>Find my VICs &rarr;</button></div>
  </section>

  <section class="step" data-step="7">
    <div class="eyebrow">Almost there</div>
    <h1 id="donetitle">Scoring your store&hellip;</h1>
    <p class="lede" id="donelede">Halia is reading your orders and grading every customer. The first run takes a minute. Keep this tab open, your hidden VICs are on their way.</p>
    <div style="display:flex;gap:12px;align-items:center;margin-top:8px" id="spinrow"><div class="spin" id="spin"></div><span id="donesub" style="color:var(--mute);font-size:14px">Connecting&hellip;</span></div>
    <div id="err7" class="err" style="display:none"></div>
    <div class="row" id="donerow" style="display:none"><a class="btn" id="openbtn" href="#">Open my dashboard &rarr;</a></div>
  </section>

</main>
<script>
var SIGNUP=__SIGNUP_REQUIRED__;
var SHOP_INSTALL=__SHOP_INSTALL_URL__;
var steps=[].slice.call(document.querySelectorAll('.step'));
var state={platform:null,source:null,myshop:'',woo_method:null,woo_token:'',shop_method:null,shop_installed:false,cur:0};
if(SIGNUP) document.getElementById('codewrap').style.display='block';
function gv(id){var e=document.getElementById(id);return e?e.value.trim():'';}
function err(id,msg){var e=document.getElementById(id);if(e){e.textContent=msg;e.style.display='block';}}
function clearErrs(){['err1','err2','err4','err6','err7'].forEach(function(i){var e=document.getElementById(i);if(e)e.style.display='none';});}
var EMRE=/^[^@\s]+@[^@\s]+\.[^@\s]+$/;
function emailRow(val){var d=document.createElement('div');d.className='emrow';
  d.innerHTML='<input type="email" placeholder="name@yourstore.com"><button type="button" class="rm" title="Remove">&times;</button>';
  d.querySelector('input').value=val||'';d.querySelector('.rm').onclick=function(){d.remove();};return d;}
function initEmails(){var l=document.getElementById('emaillist');if(l&&!l.children.length)l.appendChild(emailRow(''));}
function collectEmails(){return [].map.call(document.querySelectorAll('#emaillist input'),function(i){return i.value.trim();}).filter(Boolean);}
function renderSource(){
  var eye=document.getElementById('srceye'),ti=document.getElementById('srctitle'),le=document.getElementById('srclede'),b=document.getElementById('srcbody');
  if(state.source==='woocommerce'){
    eye.textContent='Your store data · WooCommerce';
    ti.innerHTML='Connect your orders, <em>safely.</em>';
    le.textContent='Choose how to connect. Either way Halia gets read-only access: it can read your past orders and nothing else.';
    b.innerHTML='<div class="cards">'
      +'<div class="pcard" data-wm="auto"><div class="pi">&#9889;</div><div><h3>Connect automatically</h3><p>Approve Halia inside your own WordPress admin. No keys to copy.</p></div></div>'
      +'<div class="pcard" data-wm="manual"><div class="pi">&#35;</div><div><h3>Enter an API key</h3><p>Create a read-only key in WooCommerce and paste it.</p></div></div>'
      +'</div><div id="woomethod" style="margin-top:6px"></div>';
    [].forEach.call(b.querySelectorAll('.pcard'),function(c){c.onclick=function(){
      [].forEach.call(b.querySelectorAll('.pcard'),function(x){x.classList.remove('sel');});
      c.classList.add('sel');state.woo_method=c.dataset.wm;renderWooMethod();};});
    if(state.woo_method){var sw=b.querySelector('.pcard[data-wm="'+state.woo_method+'"]');if(sw)sw.classList.add('sel');renderWooMethod();}
  } else if(state.source==='shopify'){
    eye.textContent='Your store data · Shopify';
    ti.innerHTML='Connect your orders, <em>safely.</em>';
    le.textContent='Choose how to connect. Either way Halia gets read-only access: it can read your past orders and nothing else.';
    b.innerHTML='<div class="cards">'
      +(SHOP_INSTALL?'<div class="pcard" data-sm="install"><div class="pi">&#9889;</div><div><h3>Connect with Shopify</h3><p>Add Halia from Shopify in a click. No token to copy.</p></div></div>':'')
      +'<div class="pcard" data-sm="token"><div class="pi">&#35;</div><div><h3>Enter an Admin API token</h3><p>Create a custom-app token and paste it.</p></div></div>'
      +'</div><div id="shopmethod" style="margin-top:6px"></div>';
    [].forEach.call(b.querySelectorAll('.pcard'),function(c){c.onclick=function(){
      [].forEach.call(b.querySelectorAll('.pcard'),function(x){x.classList.remove('sel');});
      c.classList.add('sel');state.shop_method=c.dataset.sm;renderShopMethod();};});
    if(state.shop_method){var ss=b.querySelector('.pcard[data-sm="'+state.shop_method+'"]');if(ss)ss.classList.add('sel');renderShopMethod();}
  } else {
    eye.textContent='Your store';
    ti.innerHTML='Which platform powers your <em>store?</em>';
    le.textContent='We could not tell automatically, no problem at all. Pick yours and we will show you exactly what to do.';
    b.innerHTML='<div class="cards"><div class="pcard" data-src="shopify"><div class="pi">S</div><div><h3>Shopify</h3><p>Connect with a read-only Admin API token.</p></div></div><div class="pcard" data-src="woocommerce"><div class="pi">W</div><div><h3>WooCommerce</h3><p>Connect with a read-only REST API key.</p></div></div></div>';
    [].forEach.call(b.querySelectorAll('.pcard'),function(c){c.onclick=function(){state.source=c.dataset.src;renderSource();};});
  }
}
function renderWooMethod(){
  var w=document.getElementById('woomethod');if(!w)return;
  if(state.woo_method==='manual'){
    w.innerHTML='<ol class="slist"><li>In your store admin, open <b>WooCommerce &rarr; Settings &rarr; Advanced &rarr; REST API</b>.</li><li>Click <b>Add key</b>. Description: "Halia". Permissions: <b>Read</b>.</li><li>Click <b>Generate API key</b>, then copy the two values.</li></ol><label>Consumer key</label><input id="consumer_key" placeholder="ck_..." autocomplete="off"><label>Consumer secret</label><input id="consumer_secret" type="password" placeholder="cs_..." autocomplete="off">';
  } else if(state.woo_method==='auto'){
    w.innerHTML='<p class="hint" style="margin-top:14px">A WooCommerce tab opens where you approve Halia. The read-only key is sent straight back, nothing to copy. Come back here when it says connected.</p><button type="button" class="btn" id="wooauth" style="margin-top:12px">Authorize in WooCommerce &rarr;</button><div id="woostatus" style="margin-top:14px"></div>';
    document.getElementById('wooauth').onclick=startWooAuth;
    if(state.woo_token)document.getElementById('woostatus').innerHTML='<span style="color:#1f564a;font:600 14px var(--sans)">&#10003; Connected. Continue when ready.</span>';
  }
}
function startWooAuth(){
  var st=document.getElementById('woostatus'),btn=document.getElementById('wooauth');
  if(!gv('store_url')){st.innerHTML='<span style="color:#8e1f0b;font-size:13.5px">Go back and enter your store address first.</span>';return;}
  btn.disabled=true;btn.innerHTML='Opening WooCommerce&hellip;';
  fetch('/v1/woo/authorize',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({store_url:gv('store_url')})})
   .then(function(r){return r.json().then(function(d){return{ok:r.ok,d:d};});})
   .then(function(res){
     if(!res.ok)throw new Error((res.d&&res.d.detail)||'Could not start.');
     state.woo_token=res.d.token;window.open(res.d.url,'_blank');
     btn.disabled=false;btn.innerHTML='Authorize in WooCommerce &rarr;';
     st.innerHTML='<div style="display:flex;gap:10px;align-items:center"><div class="spin"></div><span style="color:var(--mute);font-size:14px">Waiting for you to approve Halia in the new tab&hellip;</span></div>';
     pollWoo();
   })
   .catch(function(e){btn.disabled=false;btn.innerHTML='Authorize in WooCommerce &rarr;';st.innerHTML='<span style="color:#8e1f0b;font-size:13.5px">'+e.message+'</span>';});
}
var _wooPoll;
function pollWoo(){
  clearTimeout(_wooPoll);if(!state.woo_token)return;
  fetch('/v1/woo/authorized/'+encodeURIComponent(state.woo_token)).then(function(r){return r.json();})
   .then(function(d){var st=document.getElementById('woostatus');
     if(d&&d.ready){if(st)st.innerHTML='<span style="color:#1f564a;font:600 14px var(--sans)">&#10003; Connected. You can continue.</span>';}
     else{_wooPoll=setTimeout(pollWoo,3000);}})
   .catch(function(){_wooPoll=setTimeout(pollWoo,4000);});
}
function renderShopMethod(){
  var w=document.getElementById('shopmethod');if(!w)return;
  if(state.shop_method==='token'){
    w.innerHTML='<ol class="slist"><li>In Shopify admin, open <b>Settings &rarr; Apps and sales channels &rarr; Develop apps</b>.</li><li>Click <b>Create an app</b>, name it "Halia", then <b>Configure Admin API scopes</b>.</li><li>Tick <b>read_orders</b> and <b>read_customers</b>, save, then <b>Install app</b>.</li><li>Copy the <b>Admin API access token</b> (starts with shpat_).</li></ol><label>Your Shopify store domain</label><input id="shop_domain" placeholder="your-store.myshopify.com" autocomplete="off" value="'+(state.myshop||'')+'"><div class="hint">The .myshopify.com address, even with a custom domain.</div><label>Admin API access token</label><input id="admin_token" type="password" placeholder="shpat_..." autocomplete="off">';
  } else if(state.shop_method==='install'){
    w.innerHTML='<label>Your Shopify store domain</label><input id="shop_domain" placeholder="your-store.myshopify.com" autocomplete="off" value="'+(state.myshop||'')+'"><div class="hint">The .myshopify.com address. We open Shopify so you can add Halia, nothing to copy.</div><button type="button" class="btn" id="shopauth" style="margin-top:14px">Install Halia in Shopify &rarr;</button><div id="shopstatus" style="margin-top:14px"></div>';
    document.getElementById('shopauth').onclick=startShopInstall;
    if(state.shop_installed)document.getElementById('shopstatus').innerHTML='<span style="color:#1f564a;font:600 14px var(--sans)">&#10003; Connected. Continue when ready.</span>';
  }
}
function startShopInstall(){
  var st=document.getElementById('shopstatus'),btn=document.getElementById('shopauth');
  var dom=gv('shop_domain');
  if(!dom){st.innerHTML='<span style="color:#8e1f0b;font-size:13.5px">Enter your .myshopify.com domain first.</span>';return;}
  if(!SHOP_INSTALL){st.innerHTML='<span style="color:#8e1f0b;font-size:13.5px">Install link is not set up yet. Use the Admin API token method.</span>';return;}
  window.open(SHOP_INSTALL,'_blank');
  btn.innerHTML='Reopen Shopify &rarr;';state._dom=dom;
  st.innerHTML='<div style="display:flex;gap:10px;align-items:center"><div class="spin"></div><span style="color:var(--mute);font-size:14px">Add Halia in the new tab, then come back here&hellip;</span></div>';
  pollShopInstall();
}
var _shopPoll;
function pollShopInstall(){
  clearTimeout(_shopPoll);var dom=state._dom||gv('shop_domain');if(!dom)return;
  fetch('/v1/shopify/installed?shop='+encodeURIComponent(dom)).then(function(r){return r.json();})
   .then(function(d){var st=document.getElementById('shopstatus');
     if(d&&d.ready){state.shop_installed=true;if(d.shop_domain)state.myshop=d.shop_domain;if(st)st.innerHTML='<span style="color:#1f564a;font:600 14px var(--sans)">&#10003; Connected. You can continue.</span>';}
     else{_shopPoll=setTimeout(pollShopInstall,3000);}})
   .catch(function(){_shopPoll=setTimeout(pollShopInstall,4000);});
}
function detectThenAdvance(){
  var b=document.querySelector('.step.active [data-next]'),orig=b?b.innerHTML:'';
  if(b){b.disabled=true;b.innerHTML='Looking at your store&hellip;';}
  fetch('/v1/detect',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({store_url:gv('store_url')})})
   .then(function(r){return r.json();})
   .then(function(d){state.source=(d&&d.platform&&d.platform!=='unknown')?d.platform:'unknown';state.myshop=(d&&d.myshopify)||'';})
   .catch(function(){state.source='unknown';})
   .then(function(){if(b){b.disabled=false;b.innerHTML=orig;}show(nextFrom(1));});
}
function seq(){var s=[0,1,6,2,3];if(state.platform&&state.platform!=='later')s.push(4);s.push(5);return s;}
function order(){return seq().filter(function(x){return x!==0;});}
function show(n){
  state.cur=n;
  steps.forEach(function(s){s.classList.toggle('active',(+s.dataset.step)===n);});
  var fill=document.getElementById('barfill'),sn=document.getElementById('stepn'),o=order(),pos=o.indexOf(n);
  if(n===0){fill.style.width='6%';sn.textContent='';}
  else if(n===7){fill.style.width='100%';sn.textContent='';}
  else{fill.style.width=(((pos+1)/(o.length+1))*100)+'%';sn.textContent=(pos+1)+' of '+o.length;}
  window.scrollTo(0,0);
  if(n===2) renderSource();
  if(n===4) fillPlatform();
  if(n===6) initEmails();
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
  if(n===2){
    if(state.source==='shopify'){
      if(!state.shop_method){err('err2','Choose how to connect your store.');return false;}
      if(state.shop_method==='install'&&!state.shop_installed){err('err2','Click Install and add Halia in Shopify, then continue.');return false;}
      if(state.shop_method==='token'&&(!gv('shop_domain')||!gv('admin_token'))){err('err2','Enter your store domain and Admin API token.');return false;}}
    else if(state.source==='woocommerce'){
      if(!state.woo_method){err('err2','Choose how to connect your store.');return false;}
      if(state.woo_method==='auto'&&!state.woo_token){err('err2','Click Authorize and approve Halia in WooCommerce, then continue.');return false;}
      if(state.woo_method==='manual'&&(!gv('consumer_key')||!gv('consumer_secret'))){err('err2','Paste both your consumer key and secret.');return false;}}
    else{err('err2','Choose your store platform to continue.');return false;}
    if(SIGNUP&&!gv('code')){err('err2','Enter your signup code.');return false;}}
  if(n===4){var key=gv('api_key');if(!key){err('err4','Paste your '+(state.platform==='klaviyo'?'Klaviyo':'Mailchimp')+' key, or go back and choose to connect later.');return false;}
    if(state.platform==='klaviyo'&&key.indexOf('pk_')!==0){err('err4','A Klaviyo private key starts with pk_.');return false;}}
  if(n===6){var em=gv('email');
    if(!em){err('err6','Enter your email so we can set up your account.');return false;}
    if(!EMRE.test(em)){err('err6','That email does not look right.');return false;}
    if(collectEmails().some(function(x){return !EMRE.test(x);})){err('err6','One of the alert emails does not look right.');return false;}
    var ck=document.getElementById('accept_terms');
    if(!ck||!ck.checked){err('err6','Please accept the Terms of Service and Privacy Policy to continue.');return false;}}
  return true;
}
function nextFrom(n){var s=seq(),i=s.indexOf(n);return(i<0||i>=s.length-1)?'finish':s[i+1];}
function backFrom(n){var s=seq(),i=s.indexOf(n);return i<=0?0:s[i-1];}
function handleNext(){var n=state.cur;if(!valid(n))return;if(n===1){detectThenAdvance();return;}var t=nextFrom(n);if(t==='finish')finish();else show(t);}
[].forEach.call(document.querySelectorAll('[data-next]'),function(b){b.onclick=handleNext;});
[].forEach.call(document.querySelectorAll('[data-back]'),function(b){b.onclick=function(){show(backFrom(state.cur));};});
[].forEach.call(document.querySelectorAll('.pcard'),function(c){c.onclick=function(){
  [].forEach.call(document.querySelectorAll('.pcard'),function(x){x.classList.remove('sel');});
  c.classList.add('sel');state.platform=c.dataset.plat;document.getElementById('p3next').disabled=false;};});
document.getElementById('stage').addEventListener('keydown',function(e){
  if(e.key==='Enter'&&e.target.tagName==='INPUT'){e.preventDefault();handleNext();}});
document.getElementById('addmail').onclick=function(){var l=document.getElementById('emaillist');l.appendChild(emailRow(''));var ins=l.querySelectorAll('input');ins[ins.length-1].focus();};
function payload(){return{
  label:gv('label'),store_url:gv('store_url'),source:state.source||'',
  consumer_key:gv('consumer_key'),consumer_secret:gv('consumer_secret'),
  shop_domain:gv('shop_domain'),admin_token:gv('admin_token'),woo_token:state.woo_token||'',code:gv('code'),
  platform:(!state.platform||state.platform==='later')?'':state.platform,api_key:gv('api_key'),
  email:gv('email'),notify_emails:collectEmails(),
  accept_terms:!!(document.getElementById('accept_terms')&&document.getElementById('accept_terms').checked),
  vic_threshold:gv('vic_threshold'),sender_name:gv('sender_name'),aov:gv('aov'),max_orders:gv('max_orders'),highest_lt:gv('highest_lt')};}
function finish(){
  show(7);
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
     else if(/woocommerce|shopify|key and secret|domain|access token|signup code/i.test(m)){show(2);err('err2',m);}
     else{sp.style.display='none';document.getElementById('donesub').textContent='We hit a snag.';err('err7',m);
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
        except Exception:  # noqa: BLE001 - segments are a bonus, the key is saved
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
        import json
        return HTMLResponse(
            _WIZARD.replace("__SIGNUP_REQUIRED__", "true" if config.SIGNUP_CODE else "false")
                   .replace("__SHOP_INSTALL_URL__", json.dumps(config.HALIA_SHOPIFY_INSTALL_URL or "")))

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

        if not bool(p.get("accept_terms")):
            raise HTTPException(400, "Please accept the Terms of Service and Privacy Policy to continue.")
        terms_accepted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        import json as _json

        store = shop_store()
        store_url = g("store_url").rstrip("/")
        label = g("label")
        source = g("source").lower() or "woocommerce"
        link_token = new_token()

        if source == "shopify":
            shop_token = g("shopify_token")
            pend = _shop_pending_get(shop_token) if shop_token else None
            if pend and pend.get("token"):        # token came from the one-click OAuth install
                domain = _norm_shop(pend.get("shop_domain") or g("shop_domain") or store_url)
                admin_token = pend["token"]
            else:                                  # manual token, or a token already saved at install
                domain = _norm_shop(g("shop_domain") or store_url)
                admin_token = g("admin_token") or (store.get_token(domain) if domain else "") or ""
            if not domain or not admin_token:
                raise HTTPException(400, "Add your Shopify store domain and Admin API access token.")
            ok, why = _validate_shopify(domain, admin_token)
            if not ok:
                raise HTTPException(400, f"We could not reach Shopify with that token: {why}")
            shop = domain
            label = label or domain.replace(".myshopify.com", "")
            store.create_tenant(shop, "shopify", label, hash_token(link_token))
            store.save_shop(shop, admin_token)
            if shop_token:
                _shop_pending_pop(shop_token)
        else:
            shop = _slug(store_url)
            if not shop or not store_url.startswith("http"):
                raise HTTPException(400, "Enter your full store web address, starting with https://")
            woo_token = g("woo_token")
            pend = _woo_pending_get(woo_token) if woo_token else None
            if pend and pend.get("ck"):           # keys came from the one-click authorise flow
                ck, cs = pend["ck"], pend["cs"]
            else:                                  # manual API key
                ck, cs = g("consumer_key"), g("consumer_secret")
            if not ck or not cs:
                raise HTTPException(400, "Add your WooCommerce consumer key and secret.")
            ok, why = _validate_woo(store_url, ck, cs)
            if not ok:
                raise HTTPException(400, f"We could not reach WooCommerce with those keys: {why}")
            label = label or shop
            store.create_tenant(shop, "woocommerce", label, hash_token(link_token))
            store.save_woocommerce(shop, store_url, ck, cs)
            if woo_token:
                _woo_pending_pop(woo_token)

        from halia.api.settings import clean_emails
        acct = g("email")
        recipients = clean_emails(p.get("notify_emails"))
        if acct and acct.lower() not in (e.lower() for e in recipients):
            recipients = clean_emails([acct]) + recipients  # the owner hears about it by default
        store.save_settings(shop, _json.dumps({
            "vic_threshold": num("vic_threshold") or 5000,
            "sender_name": g("sender_name")[:120],
            "aov": num("aov"), "max_orders": int(num("max_orders")), "highest_lt": num("highest_lt"),
            "account_email": acct,
            "notify_emails": recipients,
            "notify_email": recipients[0] if recipients else "",
            "notify_enabled": bool(recipients),
            "notify_grades": ["A*", "A"],
            "terms_accepted": True,
            "terms_accepted_at": terms_accepted_at,
            "terms_version": TERMS_VERSION,
        }))
        connected, warning = _connect_marketing(store, shop, g("platform"), g("api_key"))
        _start_sync(shop, notify=True)  # warm the cache while they read the closing screen
        return {"ok": True, "link": f"/app?t={link_token}", "label": label,
                "platform_connected": connected, "platform_warning": warning}

    @app.post("/v1/detect")
    def detect_store(payload: dict = Body(...)) -> dict:
        return _detect_platform(str((payload or {}).get("store_url", "")))

    # ── WooCommerce one-click authorise (native /wc-auth flow, no plugin) ───────
    @app.post("/v1/woo/authorize")
    def woo_authorize(payload: dict = Body(...)) -> dict:
        base = config.HALIA_APP_URL or ""
        if not base.startswith("https"):
            raise HTTPException(400, "Automatic connect needs Halia running on https. "
                                     "Use the API key method instead.")
        store_url = str((payload or {}).get("store_url", "")).strip().rstrip("/")
        if not store_url.startswith("http"):
            raise HTTPException(400, "Enter your store web address first.")
        from urllib.parse import urlencode

        tok = _woo_pending_new(store_url)
        params = {"app_name": "Halia", "scope": "read", "user_id": tok,
                  "return_url": f"{base}/connect/woo/return",
                  "callback_url": f"{base}/connect/woo/callback/{tok}"}
        return {"token": tok, "url": f"{store_url}/wc-auth/v1/authorize?{urlencode(params)}"}

    @app.post("/connect/woo/callback/{token}")
    async def woo_callback(token: str, request: Request) -> dict:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            data = {}
        ck = str((data or {}).get("consumer_key", "")).strip()
        cs = str((data or {}).get("consumer_secret", "")).strip()
        if ck and cs:
            _woo_pending_set(token, ck, cs)
        return {"ok": True}

    @app.get("/v1/woo/authorized/{token}")
    def woo_authorized(token: str) -> dict:
        p = _woo_pending_get(token)
        return {"ready": bool(p and p.get("ck"))}

    @app.get("/connect/woo/return", response_class=HTMLResponse)
    def woo_return() -> HTMLResponse:
        return HTMLResponse(_page("Connected · Halia",
                                  "<h1 class=ok>&#10003; Connected</h1><p class=sub>Halia is connected "
                                  "to your store. You can close this tab and return to the setup to "
                                  "finish.</p>"))

    # ── Shopify one-click install (native OAuth, no token to copy) ──────────────
    @app.post("/v1/shopify/authorize")
    def shopify_authorize(payload: dict = Body(...)) -> dict:
        if not config.SHOPIFY_API_KEY:
            raise HTTPException(400, "One-click Shopify connect is not enabled yet. "
                                     "Use the Admin API token method.")
        base = config.HALIA_APP_URL or ""
        if not base.startswith("https"):
            raise HTTPException(400, "One-click connect needs Halia on https. "
                                     "Use the Admin API token method.")
        domain = _norm_shop(str((payload or {}).get("shop_domain", "")))
        if not domain:
            raise HTTPException(400, "Enter your Shopify store domain first.")
        from urllib.parse import urlencode

        tok = _shop_pending_new(domain)
        params = {"client_id": config.SHOPIFY_API_KEY, "scope": "read_orders,read_customers",
                  "redirect_uri": f"{base}/connect/shopify/callback", "state": tok}
        return {"token": tok, "url": f"https://{domain}/admin/oauth/authorize?{urlencode(params)}"}

    @app.get("/connect/shopify/callback", response_class=HTMLResponse)
    def shopify_callback(request: Request) -> HTMLResponse:
        q = dict(request.query_params)
        state, shop, code = q.get("state", ""), q.get("shop", ""), q.get("code", "")
        if not (_shop_pending_get(state) and shop and code):
            return HTMLResponse(_page("Halia", "<h1>Could not connect</h1><p class=sub>Please try "
                                      "again from the Halia setup.</p>"), 400)
        if not _verify_shopify_hmac(q, config.SHOPIFY_API_SECRET):
            return HTMLResponse(_page("Halia", "<h1>Could not verify</h1><p class=sub>Please try "
                                      "the Halia setup again.</p>"), 400)
        try:
            token = _shopify_exchange(shop, code)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            return HTMLResponse(_page("Halia", "<h1>Could not connect</h1><p class=sub>Please try "
                                      "again from the Halia setup.</p>"), 502)
        _shop_pending_set(state, token, shop)
        return HTMLResponse(_page("Connected · Halia",
                                  "<h1 class=ok>&#10003; Connected</h1><p class=sub>Halia is connected "
                                  "to your Shopify store. You can close this tab and return to the "
                                  "setup to finish.</p>"))

    @app.get("/v1/shopify/authorized/{token}")
    def shopify_authorized(token: str) -> dict:
        p = _shop_pending_get(token)
        return {"ready": bool(p and p.get("token")), "shop_domain": (p or {}).get("shop_domain", "")}

    # Route B: the merchant installs via your app's install link; the embedded app stores their
    # token (shopify_auth.save_shop). We just check whether that token now exists for their shop.
    @app.get("/v1/shopify/installed")
    def shopify_installed(shop: str = "") -> dict:
        domain = _norm_shop(shop)
        return {"ready": bool(domain and shop_store().get_token(domain)), "shop_domain": domain}

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
        _start_sync(shop, notify=True)  # warm the cache while they read the success page

        link = f"/app?t={token}"
        inner = (f"<h1 class=ok>✓ {html.escape(label.strip() or shop)} connected</h1>"
                 "<p class=sub>Your private dashboard is ready. Bookmark this link - it's the "
                 "only way in, so keep it safe.</p>"
                 f"<div class=card><p style='margin:0 0 14px'><a class=link href='{link}'>"
                 "Open my dashboard →</a></p>"
                 f"<div class=help>Private link</div><code>{html.escape(link)}</code></div>")
        return HTMLResponse(_page("Connected - Halia", inner))

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

        # Returning from Stripe Checkout: confirm the session, then clean the URL.
        if request.query_params.get("session_id"):
            from halia.api import billing
            billing.confirm_session(shop, request.query_params["session_id"])
            return RedirectResponse("/app", status_code=303)

        entry = cache.get(shop)
        if entry is None:
            _start_sync(shop, notify=True)
            return _preparing_page(shop)

        # Free tier: until they subscribe, show the teaser (count + latent value), not the dashboard.
        from halia.api import billing
        if not billing.is_paid(shop):
            tenant = shop_store().get_tenant(shop)
            label = (tenant["label"] if tenant else None) or shop
            p = entry["payload"]
            resp = HTMLResponse(_teaser_page(label, p.get("stat_count", "0"),
                                             p.get("stat_latent", ""), p.get("stat_toptier", "0")))
            resp.headers["Cache-Control"] = "no-store"
            return resp
        try:
            body = render_payload(entry["payload"], head_extra=_hosted_head())
        except Exception:
            traceback.print_exc()
            return HTMLResponse(_page("Halia", "<h1>Couldn't load your scores</h1>"
                                      "<p class=sub>Hit refresh in a moment.</p>"), 500)
        resp = HTMLResponse(body)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/app/status")
    def hosted_status(request: Request) -> dict:
        """Live scoring status for the preparing screen to poll."""
        shop = require_tenant(request)
        entry = cache.get(shop)
        if entry is not None:
            p = entry["payload"]
            return {"state": "done", "count": p.get("stat_count", "0"),
                    "latent": p.get("stat_latent", "")}
        _start_sync(shop, notify=True)  # keep it alive / restart if the worker died
        st = sync_status(shop)
        return {"state": st.get("state") or "running", "error": st.get("error", "")}

    @app.post("/app/refresh")
    def hosted_refresh(request: Request):
        shop = require_tenant(request)
        cache.evict(shop)
        entry = data.sync_tenant(shop)
        return {"shop": shop, "hidden_vics": len(data.hidden_results(entry)) if entry else 0}
