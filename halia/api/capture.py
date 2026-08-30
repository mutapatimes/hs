"""In-store client capture: the handover form's write-through to Shopify.

One endpoint, ``POST /v1/capture``, shared by every capture surface (the iOS handover screen
first; QR self-capture and the keyboard later). Seat-authenticated like the other extension
endpoints, so every capture is attributed to the associate who took it.

The store is the data controller and the profile's only home is the merchant's own Shopify:
Halia dedupes, writes the customer (fields + consent record + tags), sets marketing consent
only when the client opted in, scores the new profile in memory, and keeps nothing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Body, Header, HTTPException

from halia.api.shopify_auth import get_valid_token, shop_store as _ss
from halia.engine import engine

CAPTURE_TAG = "halia-captured"


def _gql(shop: str, token: str, query: str, variables: dict) -> dict:
    """One Admin GraphQL call (seam for tests)."""
    from scoring.shopify_fetch import _run, http_transport

    return _run(http_transport(shop, token), query, variables, 2)


_SEARCH = """
query($q: String!) {
  customers(first: 1, query: $q) {
    nodes { id email phone tags displayName numberOfOrders
            amountSpent { amount currencyCode }
            lastOrder { processedAt } }
  }
}"""

_CREATE = """
mutation($input: CustomerInput!) {
  customerCreate(input: $input) { customer { id } userErrors { field message } }
}"""

_UPDATE = """
mutation($input: CustomerInput!) {
  customerUpdate(input: $input) { customer { id } userErrors { field message } }
}"""

_TAGS_ADD = """
mutation($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) { userErrors { message } }
}"""

_METAFIELDS_SET = """
mutation($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) { userErrors { field message } }
}"""

_EMAIL_CONSENT = """
mutation($input: CustomerEmailMarketingConsentUpdateInput!) {
  customerEmailMarketingConsentUpdate(input: $input) { userErrors { field message } }
}"""

_SMS_CONSENT = """
mutation($input: CustomerSmsMarketingConsentUpdateInput!) {
  customerSmsMarketingConsentUpdate(input: $input) { userErrors { field message } }
}"""


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _find_existing(shop: str, token: str, email: str, phone: str) -> Optional[dict]:
    """Dedupe: the customer this email/phone already belongs to, if any."""
    for q in ([f'email:"{email}"'] if email else []) + ([f'phone:"{phone}"'] if phone else []):
        try:
            nodes = ((_gql(shop, token, _SEARCH, {"q": q}) or {}).get("customers") or {}).get("nodes") or []
        except Exception:  # noqa: BLE001 — a failed search must not block a capture
            nodes = []
        if nodes:
            return nodes[0]
    return None


def existing_match(shop: str, email: str, phone: str) -> Optional[dict]:
    """Who this email or phone already belongs to, described so an associate can tell whether it
    is the same person. Shopify tenants only; returns None when nothing matches."""
    token = get_valid_token(shop)
    if not token or not (email or phone):
        return None
    node = _find_existing(shop, token, email, phone)
    if not node:
        return None
    by = "email" if (email and (node.get("email") or "").lower() == email.lower()) else "phone"
    spent = (node.get("amountSpent") or {}).get("amount")
    return {"cid": str(node.get("id") or ""), "name": node.get("displayName") or "",
            "email": node.get("email") or "", "phone": node.get("phone") or "",
            "orders": int(node.get("numberOfOrders") or 0),
            "spent": spent, "currency": (node.get("amountSpent") or {}).get("currencyCode") or "",
            "last": ((node.get("lastOrder") or {}).get("processedAt") or "")[:10],
            "by": by}


def _score_capture(cid: str, body: dict, email: str, phone: str) -> dict:
    """Grade the freshly captured profile in memory (nothing stored)."""
    record = {
        "CUST_ID": cid,
        "EMAIL_ADDR": email,
        "PHONE": phone,
        "COMPANY_NAME": _clean(body.get("company")),
        "LATEST_SHIPPING_ADDRESS1": _clean(body.get("address")),
        "LATEST_SHIPPING_ADDRESS2": _clean(body.get("city")),
        "LATEST_SHIPPING_ADDRESS4": _clean(body.get("country")),
        "LATEST_SHIPPING_ZIP": _clean(body.get("postcode")),
        "LATEST_BILLING_ZIP": _clean(body.get("postcode")),
        "ORDER_NOTE": _clean(body.get("notes")),
    }
    try:
        r = engine.score_one(record)
        return {"grade": r.grade, "score": r.score, "signals": r.signals, "reasons": r.reasons}
    except Exception:  # noqa: BLE001 — scoring is a bonus on this path, never a blocker
        return {}


def _perform_capture_woo(shop: str, body: dict, channel: str, email: str, phone: str,
                         associate: str, seat_id: str) -> dict:
    """The WooCommerce path: the customer record plus Halia's capture record and preferences in
    the customer's meta, in the merchant's own store. Marketing consent has no native home in WC,
    so it lives in the capture record and, when Mailchimp is connected, the opted-in client joins
    the store's audience."""
    from halia.api.board import woo_sink

    sink = woo_sink(shop)
    first, last = _clean(body.get("first_name")), _clean(body.get("last_name"))
    consent = body.get("consent") or {}
    wants_email = bool(consent.get("email_marketing")) and bool(email)
    wants_sms = bool(consent.get("sms_marketing")) and bool(phone)
    now = datetime.now(timezone.utc).isoformat()
    record = {"channel": channel, "at": now, "associate": associate, "seat_id": seat_id,
              "consent_text": _clean(body.get("consent_text")) or "Saved to look after you as a client",
              "email_marketing": wants_email, "sms_marketing": wants_sms,
              "location": _clean(body.get("location"))}
    prefs = {k: _clean(body.get(k)) for k in ("sizes", "preferences", "occasion", "birthday") if _clean(body.get(k))}
    fields = {"first_name": first, "last_name": last, "email": email, "phone": phone,
              "address": _clean(body.get("address")), "city": _clean(body.get("city")),
              "postcode": _clean(body.get("postcode"))}
    existing = sink.find_customer(email, phone)
    created = existing is None
    tags = [CAPTURE_TAG, f"halia-capture-{channel}"]
    meta = {"halia_capture": json.dumps(record), "halia_tags": json.dumps(tags)}
    if prefs:
        meta["halia_preferences"] = json.dumps(prefs)
    if created:
        cust = sink.create_customer({**fields, "meta": meta})
        wid = str(cust["id"])
    else:
        wid = str(existing["id"])
        cur = existing.get("meta_data") or []
        old_tags = next((m.get("value") for m in cur if m.get("key") == "halia_tags"), None)
        try:
            old_tags = json.loads(old_tags) if isinstance(old_tags, str) else (old_tags or [])
        except (TypeError, ValueError):
            old_tags = []
        meta["halia_tags"] = json.dumps(list(dict.fromkeys(list(old_tags) + tags)))
        keep = {k: v for k, v in fields.items() if v and not (k == "email" and existing.get("email"))}
        sink.update_customer(wid, {**keep, "meta": meta})
    sink.index_add("captured", wid)
    if wants_email:
        try:
            conn = _ss().get_mailchimp(shop)
            if conn and conn.get("api_key") and conn.get("list_id"):
                from halia.adapters.mailchimp_sink import MailchimpSink
                MailchimpSink(conn["api_key"], conn["list_id"]).add_member(
                    email, first, last, tags=["Halia captured"])
        except Exception:  # noqa: BLE001 — the audience is a bonus, the capture is the point
            pass
    out = {"ok": True, "created": created, "customer_id": wid}
    out.update(_score_capture(wid, body, email, phone))
    try:
        from halia.api import birthdays, reports
        reports.invalidate(shop)
        birthdays.invalidate(shop)
    except Exception:  # noqa: BLE001
        pass
    return out


def perform_capture(shop: str, body: dict, channel: str,
                    associate: str = "", seat_id: str = "", mode: str = "auto") -> dict:
    """The shared pipeline: dedupe -> write -> consent -> tags -> score. Used by the seat-authed
    endpoint (handover, keyboard, vcard) and the public QR self-capture form alike.

    ``mode`` is the associate's decision when the details match someone already in the book:
    "auto"/"merge" adds to that record (the default, and what the unattended QR form does),
    "new" keeps them apart as a separate client, tagged so the merchant can reconcile later.
    """
    from halia.capture_quality import clean_email, clean_postcode

    email, _, _ = clean_email(body.get("email"), check_dns=False)
    phone = _clean(body.get("phone"))
    if not email and not phone:
        raise HTTPException(422, "Capture needs at least an email or a phone number")
    # A tidied postcode both stores better and scores better (the property signals read it).
    pc, _ = clean_postcode(body.get("postcode"), body.get("country"))
    if pc:
        body = {**body, "postcode": pc}

    from halia.api.shopify_auth import shop_store as _ss
    tenant = dict(_ss().get_tenant(shop) or {})
    if tenant.get("kind") == "woocommerce":
        return _perform_capture_woo(shop, body, channel, email, phone, associate, seat_id)

    token = get_valid_token(shop)
    if not token:
        raise HTTPException(409, "This store has no Shopify connection to save the client into")

    first, last = _clean(body.get("first_name")), _clean(body.get("last_name"))
    consent = body.get("consent") or {}
    wants_email = bool(consent.get("email_marketing")) and bool(email)
    wants_sms = bool(consent.get("sms_marketing")) and bool(phone)

    existing = None if mode == "new" else _find_existing(shop, token, email, phone)
    created = existing is None

    # The customer write: create, or update only the fields the form actually provided.
    cust_input: dict = {}
    for key, val in (("firstName", first), ("lastName", last),
                     ("email", email), ("phone", phone)):
        if val:
            cust_input[key] = val
    if _clean(body.get("notes")) and created:
        cust_input["note"] = _clean(body.get("notes"))
    addr = {k: v for k, v in (("address1", _clean(body.get("address"))),
                              ("city", _clean(body.get("city"))),
                              ("zip", _clean(body.get("postcode"))),
                              ("country", _clean(body.get("country")))) if v}
    if addr and created:
        cust_input["addresses"] = [addr]

    if created:
        cust_input["tags"] = [CAPTURE_TAG, f"halia-capture-{channel}"] + (
            ["halia-possible-duplicate"] if mode == "new" else [])
        data_ = _gql(shop, token, _CREATE, {"input": cust_input})
        node = (data_ or {}).get("customerCreate") or {}
    else:
        cust_input["id"] = existing["id"]
        # Never clobber an existing email/phone with a duplicate-key error: keep only new ones.
        if _clean(existing.get("email")):
            cust_input.pop("email", None)
        if _clean(existing.get("phone")):
            cust_input.pop("phone", None)
        data_ = _gql(shop, token, _UPDATE, {"input": cust_input})
        node = (data_ or {}).get("customerUpdate") or {}

    errs = node.get("userErrors") or []
    cid = ((node.get("customer") or {}).get("id")) or (existing or {}).get("id")
    if errs or not cid:
        raise HTTPException(502, "Shopify declined the profile: "
                            + "; ".join(e.get("message", "") for e in errs) if errs
                            else "Shopify returned no customer id")

    # Tags on the update path (create carries them inline).
    if not created:
        try:
            _gql(shop, token, _TAGS_ADD,
                 {"id": cid, "tags": [CAPTURE_TAG, f"halia-capture-{channel}"]})
        except Exception:  # noqa: BLE001
            pass

    # The consent record + preferences live on the customer, in the merchant's own store.
    now = datetime.now(timezone.utc).isoformat()
    capture_record = {
        "channel": channel, "at": now,
        "associate": associate, "seat_id": seat_id,
        "consent_text": _clean(body.get("consent_text")) or
        "Saved to look after you as a client",
        "email_marketing": wants_email, "sms_marketing": wants_sms,
        "location": _clean(body.get("location")),
    }
    prefs = {k: _clean(body.get(k)) for k in ("sizes", "preferences", "occasion", "birthday")
             if _clean(body.get(k))}
    metafields = [{"ownerId": cid, "namespace": "halia", "key": "capture",
                   "type": "json", "value": json.dumps(capture_record)}]
    if prefs:
        metafields.append({"ownerId": cid, "namespace": "halia", "key": "preferences",
                           "type": "json", "value": json.dumps(prefs)})
    try:
        _gql(shop, token, _METAFIELDS_SET, {"metafields": metafields})
    except Exception:  # noqa: BLE001
        pass

    # Marketing consent, only where the client opted in — written to Shopify's native
    # consent fields so Klaviyo and every downstream tool respect it.
    if wants_email:
        try:
            _gql(shop, token, _EMAIL_CONSENT, {"input": {
                "customerId": cid,
                "emailMarketingConsent": {"marketingState": "SUBSCRIBED",
                                          "marketingOptInLevel": "SINGLE_OPT_IN",
                                          "consentUpdatedAt": now}}})
        except Exception:  # noqa: BLE001
            pass
    if wants_sms:
        try:
            _gql(shop, token, _SMS_CONSENT, {"input": {
                "customerId": cid,
                "smsMarketingConsent": {"marketingState": "SUBSCRIBED",
                                        "marketingOptInLevel": "SINGLE_OPT_IN",
                                        "consentUpdatedAt": now}}})
        except Exception:  # noqa: BLE001
            pass

    out = {"ok": True, "created": created, "customer_id": cid}
    out.update(_score_capture(cid, body, email, phone))
    try:
        from halia.api import birthdays, reports
        reports.invalidate(shop)
        birthdays.invalidate(shop)
    except Exception:  # noqa: BLE001
        pass
    return out


# ── QR self-capture ──────────────────────────────────────────────────────────

_SLUG_CACHE: dict = {}   # slug -> shop (small tenant counts; rebuilt lazily)


def _settings(shop: str) -> dict:
    from halia.api.shopify_auth import shop_store

    raw = shop_store().get_settings_raw(shop)
    return json.loads(raw) if raw else {}


def _slug_for(shop: str) -> str:
    """The shop's stable self-capture slug, minted on first use."""
    from halia.api.shopify_auth import shop_store

    d = _settings(shop)
    slug = d.get("capture_slug")
    if not slug:
        import secrets

        slug = secrets.token_urlsafe(12)
        d["capture_slug"] = slug
        shop_store().save_settings(shop, json.dumps(d))
    _SLUG_CACHE[slug] = shop
    return slug


def _shop_for_slug(slug: str):
    from halia.api.shopify_auth import shop_store

    if slug in _SLUG_CACHE:
        return _SLUG_CACHE[slug]
    for t in shop_store().all_tenants():
        if _settings(t["shop"]).get("capture_slug") == slug:
            _SLUG_CACHE[slug] = t["shop"]
            return t["shop"]
    return None


_QR_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>{store}</title><style>
  *{{box-sizing:border-box}} body{{margin:0;background:#f8f7f5;color:#1a1a1d;
    font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
  .wrap{{max-width:430px;margin:0 auto;padding:34px 22px 60px}}
  h1{{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:27px;margin:0 0 6px}}
  .sub{{color:#6b6b70;font-size:14px;margin:0 0 26px}}
  label{{display:block;font-size:12.5px;font-weight:600;margin:14px 0 5px}}
  .why{{font-weight:500;color:#8b8b90}} .grp{{margin-top:20px}}
  input{{width:100%;padding:12px 13px;border:1px solid #d6d5d1;border-radius:10px;background:#fff;
    font:inherit;font-size:16px;outline:none}} input:focus{{border-color:#8a8a8e}}
  .tgl{{display:flex;gap:10px;align-items:flex-start;margin:16px 0 0;font-size:14px;color:#3d3d40}}
  .tgl input{{width:18px;height:18px;margin-top:2px;flex:0 0 auto}}
  .foot{{color:#8b8b90;font-size:12.5px;margin-top:18px}}
  button{{width:100%;margin-top:22px;padding:15px;border:0;border-radius:12px;background:#1a1a1d;
    color:#fff;font:600 16px inherit;cursor:pointer}}
  .done{{text-align:center;padding-top:14vh}} .done h1{{font-size:30px}}
</style></head><body><div class="wrap" id="w">
 <h1>{store}</h1><p class="sub">Leave your details and we&rsquo;ll look after you.</p>
 <form id="f">
  <label>First name</label><input name="first_name" autocomplete="given-name">
  <label>Last name</label><input name="last_name" autocomplete="family-name">
  <label>Phone</label><input name="phone" type="tel" autocomplete="tel">
  <label>Email</label><input name="email" type="email" autocomplete="email">
  <label>Birthday <span class="why">for a birthday treat</span></label><input name="birthday" placeholder="14 June">
  <label class="grp">Delivery address <span class="why">for gifts, deliveries and event invitations</span></label>
  <input name="address" placeholder="Street address" autocomplete="street-address" style="margin-bottom:8px">
  <input name="postcode" placeholder="Postcode" autocomplete="postal-code" style="margin-bottom:8px">
  <input name="city" placeholder="City" autocomplete="address-level2">
  <label>Sizes, likes, occasions (optional)</label><input name="preferences">
  <div id="sug" style="display:none;margin-top:7px;font-size:13.5px;color:#1f564a;cursor:pointer;font-weight:600"></div>
  <label class="tgl"><input type="checkbox" name="em">Email me about new arrivals and events</label>
  <label class="tgl"><input type="checkbox" name="sm">Text me occasionally</label>
  <p class="foot">Kept by {store} for personal service.</p>
  <button type="submit">Save my details</button>
 </form>
</div><script>
var F=document.getElementById('f'),SG=document.getElementById('sug');
function EP(p){{var q=new URLSearchParams(location.search).get('halia-page');return q?location.pathname+'?halia-page='+q+p:location.pathname+p;}}
function check(fields){{return fetch(EP('/check'),{{method:'POST',
  headers:{{'Content-Type':'application/json'}},body:JSON.stringify(fields)}})
  .then(function(r){{return r.json();}});}}
F.email.addEventListener('blur',function(){{var v=F.email.value.trim();
  SG.style.display='none';
  if(!v)return;
  check({{email:v}}).then(function(d){{
    if(d.email_suggestion){{SG.textContent='Did you mean '+d.email_suggestion+'?';
      SG.style.display='block';
      SG.onclick=function(){{F.email.value=d.email_suggestion;SG.style.display='none';}};}}
  }}).catch(function(){{}});}});
F.postcode.addEventListener('blur',function(){{var v=F.postcode.value.trim();
  if(!v)return;
  check({{postcode:v}}).then(function(d){{if(d.postcode)F.postcode.value=d.postcode;}})
  .catch(function(){{}});}});
document.getElementById('f').addEventListener('submit',function(e){{e.preventDefault();
  var f=e.target,b={{channel:'qr',by:new URLSearchParams(location.search).get('by')||''}};
  ['first_name','last_name','phone','email','birthday','address','postcode','city','preferences'].forEach(function(k){{
    if(f[k].value.trim())b[k]=f[k].value.trim();}});
  if(!b.phone&&!b.email){{alert('A phone number or email is needed.');return;}}
  b.consent={{email_marketing:f.em.checked,sms_marketing:f.sm.checked}};
  var btn=f.querySelector('button');btn.disabled=true;btn.textContent='Saving\u2026';
  fetch(EP(''),{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify(b)}}).then(function(r){{if(!r.ok)throw 0;
    document.getElementById('w').innerHTML='<div class="done"><h1>Thank you</h1>'+
      '<p class="sub">You are in good hands.</p></div>';}})
  .catch(function(){{btn.disabled=false;btn.textContent='Save my details';
    alert('Could not save just now. Please try again.');}});
}});
</script></body></html>"""


def _check_fields(body: dict) -> dict:
    """{email_ok, email_suggestion, postcode_ok, postcode} for whatever fields were sent."""
    from halia.capture_quality import clean_email, clean_postcode

    out: dict = {}
    if _clean(body.get("email")):
        email, suggestion, ok = clean_email(body.get("email"))
        out.update({"email_ok": bool(ok), "email_suggestion": suggestion})
    if _clean(body.get("postcode")):
        pc, ok = clean_postcode(body.get("postcode"), body.get("country"))
        out.update({"postcode_ok": bool(ok), "postcode": pc})
    return out


def render_capture(slug: str):
    """The store-voiced self-capture form. Served on the store's own domain wherever possible."""
    from fastapi.responses import HTMLResponse

    from halia.api.shopify_auth import shop_store

    shop = _shop_for_slug(slug)
    if not shop:
        raise HTTPException(404, "Unknown link")
    tenant = dict(shop_store().get_tenant(shop) or {})
    store = (tenant.get("label") or shop).strip()
    return HTMLResponse(_QR_PAGE.format(store=store))


def submit_public(slug: str, body: Any) -> dict:
    shop = _shop_for_slug(slug)
    if not shop:
        raise HTTPException(404, "Unknown link")
    if not isinstance(body, dict):
        raise HTTPException(422, "Body must be a JSON object")
    out = perform_capture(shop, body, "qr", associate=_clean(body.get("by")))
    # Unattended capture: a qualifying new client pings the team (best-effort).
    from halia.api.capture_alerts import dispatch_capture_alert

    dispatch_capture_alert(shop, out, body, "qr")
    # The public form gets a plain thank-you: no grade, no customer id.
    return {"ok": True}


def check_public(slug: str, body: Any) -> dict:
    """Live field hygiene for the self-capture form: a typo suggestion the client can
    accept while still present. Validates only what was sent; returns nothing else."""
    if not _shop_for_slug(slug):
        raise HTTPException(404, "Unknown link")
    return _check_fields(body if isinstance(body, dict) else {})


def register(app) -> None:
    @app.post("/v1/capture")
    def capture(body: Any = Body(...),
                x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        from halia.api.extension import _resolve_ext

        auth = _resolve_ext(x_halia_ext_token)
        if not isinstance(body, dict):
            raise HTTPException(422, "Body must be a JSON object")
        channel = _clean(body.get("channel")) or "handover"
        mode = _clean(body.get("mode")) or "auto"
        if mode not in ("auto", "merge", "new"):
            raise HTTPException(422, "mode must be auto, merge or new")
        return perform_capture(auth.shop, body, channel, associate=auth.seat_name or "",
                               seat_id=auth.seat_id or "", mode=mode)

    @app.post("/v1/capture/followup")
    def capture_followup(body: Any = Body(...),
                         x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """After a capture: put the client on the pipeline's first column with the associate's
        note, so the follow-up happens the same day instead of never."""
        from halia.api.board import _sink, _write_soft, append_activity, load_pipe
        from halia.api.extension import _resolve_ext
        from scoring.shopify_pipeline import STAGES, stage_tag

        auth = _resolve_ext(x_halia_ext_token)
        cid = _clean((body or {}).get("customer_id")).rsplit("/", 1)[-1]
        if not cid:
            raise HTTPException(422, "customer_id is required")
        note = _clean((body or {}).get("note"))[:2000]
        due = _clean((body or {}).get("due"))[:10] or None
        if due:
            import datetime as _dt
            try:
                _dt.date.fromisoformat(due)
            except ValueError:
                raise HTTPException(422, "due must be a date, YYYY-MM-DD")
            note = f"Follow up week of {due}: {note}" if note else f"Follow up week of {due}"
        sink = _sink(auth.shop)
        pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
        stage = STAGES[0]
        pipe["stage"] = stage
        if due:
            pipe["due"] = due
        append_activity(pipe, "added", auth.seat_id, auth.seat_name or "A team member",
                        note=note or "Met in store, follow up today")
        sink.untag_customer(cid, [stage_tag(s) for s in STAGES if s != stage])
        sink.tag_customer(cid, [stage_tag(stage)])
        _write_soft(sink, cid, pipe)
        try:
            from halia.api import reports
            reports.invalidate(auth.shop)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "stage": stage, "due": due}

    @app.get("/v1/capture/link")
    def capture_link(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """The shop's self-capture URL (for the in-app QR and printable cards)."""
        from urllib.parse import quote

        from halia import config
        from halia.api.extension import _resolve_ext

        from halia.api.client_host import client_url

        auth = _resolve_ext(x_halia_ext_token)
        path = f"c/{_slug_for(auth.shop)}" + (("?by=" + quote(auth.seat_name)) if auth.seat_name else "")
        return {"url": client_url(auth.shop, path)}

    @app.post("/c/{slug}/check", include_in_schema=False)
    def capture_check(slug: str, body: Any = Body(...)) -> dict:
        return check_public(slug, body)

    @app.post("/v1/capture/check")
    def capture_check_seat(body: Any = Body(...),
                           x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        from halia.api.extension import _resolve_ext

        auth = _resolve_ext(x_halia_ext_token)
        b = body if isinstance(body, dict) else {}
        out = _check_fields(b)
        # Does this person look like someone already in the book? The associate decides what to do;
        # the public QR form never sees this, so a stranger cannot probe who is on file.
        try:
            from halia.capture_quality import clean_email
            email, _, _ = clean_email(b.get("email"), check_dns=False)
            out["match"] = existing_match(auth.shop, email, _clean(b.get("phone")))
        except Exception:  # noqa: BLE001 — a failed search must never block the form
            out["match"] = None
        return out

    @app.get("/c/{slug}", include_in_schema=False)
    def capture_page(slug: str):
        return render_capture(slug)

    @app.post("/c/{slug}", include_in_schema=False)
    def capture_submit(slug: str, body: Any = Body(...)) -> dict:
        return submit_public(slug, body)
