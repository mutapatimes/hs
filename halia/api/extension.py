"""Browser-extension API: a per-merchant token plus a single-customer grade lookup.

The Halia badge extension (see the extension/ directory) puts a client's grade into the surfaces
an associate already works in: the store admin, WhatsApp Web, Gmail. It authenticates with a
long-lived per-tenant token (minted here, shown once in Settings) and asks this endpoint for one
customer's grade at a time.

Zero-retention is untouched. The lookup reads the shop's existing RAM cache (the same warm scored
book the dashboard uses), or scores a single customer live, and stores nothing about the customer.
Only the sha256 hash of the token is persisted, exactly like the self-service tenant link token.

    POST /v1/extension/token   — mint (or rotate) this tenant's extension token (require_shop)
    GET  /v1/extension/token   — whether a token exists, and the API base (require_shop)
    POST /v1/extension/lookup  — one customer's grade, authed by the X-Halia-Ext-Token header
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Body, Depends, Header, HTTPException, Query

from halia import config
from halia.api import data
from halia.api.shopify_auth import get_valid_token, require_shop, shop_store
from halia.api.tenant_auth import hash_token, new_token


# ── the "play" a client falls into, mirrored from playOf() in web/template.html ──────
_PLAY = {
    "sleeping": {"label": "Gone quiet",
                 "action": "A proven client who has gone quiet. Reach out personally to bring them back."},
    "fresh": {"label": "Fresh",
              "action": "A new potential VIC. Welcome them personally and lead with service."},
    "": {"label": "", "action": ""},
}


def _play_of(row: dict) -> str:
    tier, band = row.get("tier"), row.get("band")
    if row.get("known") or (tier in ("A1", "A") and (row.get("ordersCount") or 0) >= 2
                            and band == "lapsed"):
        return "sleeping"
    if not row.get("known") and band in ("active", "new"):
        return "fresh"
    return ""


def _fill(text: str, first, sender: str, catalog) -> str:
    """Fill template tokens. first=None leaves {first_name} for the toolbar to fill per client."""
    t = text or ""
    if first is not None:
        t = t.replace("{first_name}", first or "there")
    t = t.replace("{sender}", sender or "")
    if catalog:
        t = t.replace("{catalog_link}", catalog)
    return t


def _templates(shop: str, first_name, catalog=None, sender: str | None = None) -> list[dict]:
    """The merchant's own editable outreach templates, with placeholders filled for this client.
    ``sender`` overrides the store sign-off with the signed-in associate's own."""
    from halia.api.settings import settings_for
    s = settings_for(shop)
    sender = sender if sender else (s.get("sender_name") or "")
    cat = catalog if catalog is not None else _catalog_link(shop)
    out = []
    for t in (s.get("email_templates") or [])[:60]:
        out.append({"name": t.get("name", ""),
                    "category": t.get("category", "") or "General",
                    "subject": _fill(t.get("subject", ""), first_name, sender, cat),
                    "body": _fill(t.get("body", ""), first_name, sender, cat)})
    return out


def _dashboard_link() -> str:
    return (config.HALIA_APP_URL or "").rstrip("/") + "/app"


def _last_outreach(activity: list) -> Optional[dict]:
    """The most recent outreach (contacted / note) from a pipeline activity log, so the toolbar can
    warn 'already contacted' before someone messages again. None if the client has never been touched."""
    last = None
    for a in activity or []:
        if a.get("action") in ("contacted", "note"):
            if last is None or (a.get("at") or "") > (last.get("at") or ""):
                last = a
    if not last:
        return None
    return {"at": last.get("at"), "by": last.get("actor_name"),
            "action": last.get("action"), "note": last.get("note")}


def _todos(shop: str) -> list[dict]:
    """Team to-dos from the scored book: fresh orders from top clients to acknowledge, and proven
    clients gone quiet to win back. Warm cache only, so this is cheap. No customer data stored."""
    import time
    from halia.cache import cache
    rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []
    now = time.time()
    out = []
    for r in rows:
        name = r.get("name") or "A client"
        grade = r.get("grade") or ""
        ls = r.get("lastSort") or 0
        recent = ls and (now - ls) <= 7 * 86400
        top = str(r.get("tier") or "").startswith("A")
        if top and r.get("band") == "active" and recent:
            out.append({"kind": "new_order", "cid": r.get("cid"), "name": name, "grade": grade,
                        "text": f"New order · {name} ({grade}) · send a personal note"})
        elif _play_of(r) == "sleeping":
            out.append({"kind": "gone_quiet", "cid": r.get("cid"), "name": name, "grade": grade,
                        "text": f"Gone quiet · {name} ({grade}) · reach out"})
    # Birthdays in the next week ride the same queue: the easiest note of the year to send.
    try:
        from halia.api.birthdays import upcoming
        for b in upcoming(shop, 7)[:5]:
            when = "today" if b["in_days"] == 0 else ("tomorrow" if b["in_days"] == 1 else f"in {b['in_days']} days")
            out.append({"kind": "birthday", "cid": b["cid"], "name": b["name"], "grade": b.get("grade") or "",
                        "why": f"Birthday {when}", "reason": f"Birthday {when}", "template": "A birthday note"})
    except Exception:  # noqa: BLE001 — birthdays are a bonus on this queue
        pass
    out.sort(key=lambda t: {"new_order": 0, "birthday": 1}.get(t["kind"], 2))
    return out[:15]


def _woo_store(shop: str) -> Optional[str]:
    """The WooCommerce storefront origin for a tenant on Woo, else None."""
    try:
        tenant = dict(shop_store().get_tenant(shop) or {})
        if tenant.get("kind") != "woocommerce":
            return None
        creds = shop_store().get_woocommerce(shop)
        return (creds or {}).get("store_url", "").rstrip("/") or None
    except Exception:  # noqa: BLE001
        return None


def woo_cart_url(store: str, items: list[tuple[str, int]]) -> tuple[str, bool]:
    """A WooCommerce cart link. One item uses core's add-to-cart; several need the optional
    helper (halia-cart=). Returns (url, needs_helper)."""
    items = [(str(pid), max(1, int(q or 1))) for pid, q in items if str(pid).strip()]
    if len(items) == 1:
        pid, q = items[0]
        return f"{store}/?add-to-cart={pid}&quantity={q}", False
    return f"{store}/?halia-cart=" + ",".join(f"{pid}:{q}" for pid, q in items), True


def _cart_base(shop: str) -> str:
    """The storefront origin for a Shopify /cart permalink: the primary domain, else myshopify."""
    woo = _woo_store(shop)
    if woo:
        return woo
    dom = ""
    try:
        from halia.api.catalog import _primary_domain
        dom = _primary_domain(shop) or ""
    except Exception:
        dom = ""
    if not dom:
        dom = shop if shop.endswith(".myshopify.com") else f"{shop}.myshopify.com"
    return "https://" + dom


def _catalog_link(shop: str) -> Optional[str]:
    from halia.api.catalog import catalog_url_for
    try:
        return catalog_url_for(shop) or None
    except Exception:
        return None


def _cart(row: dict) -> Optional[dict]:
    """A compact open-basket (abandoned checkout), if the client has one, for the badge."""
    c = row.get("cart")
    if not isinstance(c, dict) or not (c.get("value") or 0) > 0:
        return None
    return {"value": c.get("value"), "count": c.get("count"), "url": c.get("url")}


def _resp_from_row(shop: str, row: dict) -> dict:
    """The lookup response built from a warm payload client row (has latent, reasons, reco)."""
    play = _play_of(row)
    first = (row.get("name") or "").split(" ")[0]
    return {
        "found": True,
        "cid": row.get("cid"),
        "name": row.get("name"),
        "email": row.get("email"),
        "phone": row.get("phone"),
        "grade": row.get("grade"),
        "tier": row.get("tier"),
        "score": row.get("score"),
        "band": row.get("band"),
        "hidden": not row.get("known"),
        "latent": row.get("latent"),
        "spend": row.get("spend"),
        "ordersCount": row.get("ordersCount"),
        "last": row.get("last"),
        "cart": _cart(row),
        "reasons": [s.get("d") for s in (row.get("signals") or []) if s.get("d")],
        "reco": row.get("reco"),
        "play": play,
        "playLabel": _PLAY[play]["label"],
        "action": _PLAY[play]["action"] or row.get("reco"),
        "adminUrl": row.get("adminUrl"),
        "dashboard": _dashboard_link(),
        "catalog": _catalog_link(shop),
        "templates": _templates(shop, first),
        "suggested": _suggest_templates(shop, {**{"cid": row.get("cid"), "found": True, "play": play, "grade": row.get("grade"), "ordersCount": row.get("ordersCount"), "cart": _cart(row)}}, _templates(shop, first)),
    }


def _resp_from_result(shop: str, r) -> dict:
    """The lookup response for a single customer scored live on a cold-cache miss."""
    reasons = [x.strip() for x in (r.reasons or "").replace(";", "\n").split("\n") if x.strip()]
    return {
        "found": True,
        "cid": getattr(r, "customer_id", None),
        "name": None,
        "email": r.email,
        "phone": getattr(r, "phone", None),
        "grade": r.grade,
        "tier": r.tier,
        "score": r.score,
        "band": None,
        "hidden": bool(r.hidden_vic),
        "latent": None,
        "spend": r.spend,
        "ordersCount": None,
        "last": None,
        "cart": None,
        "reasons": reasons,
        "reco": r.gesture,
        "play": "",
        "playLabel": "",
        "action": r.gesture,
        "adminUrl": None,
        "dashboard": _dashboard_link(),
        "catalog": _catalog_link(shop),
        "templates": _templates(shop, ""),
        "suggested": _suggest_templates(shop, {"found": False}, _templates(shop, "")),
    }


def _digits(v: str) -> str:
    """The trailing national digits of a phone, so +44 20 7... and 020 7... compare equal."""
    d = "".join(ch for ch in str(v or "") if ch.isdigit())
    return d[-9:] if len(d) >= 9 else d


def _e164(v) -> str:
    """Full international digits (country code, no plus) for iOS Call Directory, which matches
    incoming calls in E.164 and needs the whole number. Only numbers stored with an international
    prefix (+ or 00) are trustworthy here; a bare local number cannot be matched against an
    incoming E.164 call, so it is skipped rather than guessed. Returns '' when not usable."""
    s = str(v or "").strip()
    if not s:
        return ""
    intl = s.startswith("+") or s.startswith("00")
    digits = "".join(ch for ch in s if ch.isdigit())
    if s.startswith("00"):
        digits = digits[2:]
    if not intl or len(digits) < 8:
        return ""
    return digits


_HANDLE_RE = re.compile(r"/products/([A-Za-z0-9][A-Za-z0-9\-_]*)")


def _handle_from_url(u) -> str:
    """The product handle from a storefront URL (…/products/<handle>?variant=…), or a bare handle.
    Powers the iOS 'save a product while browsing' flow: the app stores the URL, this reads it."""
    s = str(u or "").split("?", 1)[0].split("#", 1)[0].strip().rstrip("/")
    if not s:
        return ""
    m = _HANDLE_RE.search(s)
    if m:
        return m.group(1).lower()
    if "/" not in s and re.match(r"^[A-Za-z0-9][A-Za-z0-9\-_]*$", s):
        return s.lower()                             # a bare handle passed directly
    return ""


def _products_for_handles(shop: str, handles: list[str]) -> list[dict]:
    """Resolve storefront handles to product cards (product_search_node dicts, with variants),
    preserving order, via one Shopify product search. Shopify-only; returns [] for a read-only /
    non-Shopify tenant or on any fetch hiccup. Shared by the catalogue, product-grid and cart-link
    'from URLs' endpoints."""
    token = get_valid_token(shop)
    if not token or not handles:
        return []
    from scoring.shopify_fetch import _run, http_transport
    from scoring.shopify_graphql import PRODUCT_SEARCH_QUERY, product_search_node
    q = " OR ".join("handle:" + h for h in handles[:40])
    try:
        data_ = _run(http_transport(shop, token), PRODUCT_SEARCH_QUERY, {"q": q, "n": min(len(handles), 40)}, 2)
    except Exception:
        return []
    by_handle = {}
    for node in (((data_ or {}).get("products") or {}).get("nodes")) or []:
        p = product_search_node(node)
        if p.get("handle"):
            by_handle[p["handle"].lower()] = p
    return [by_handle[h] for h in handles if h in by_handle]


def _ids_for_handles(shop: str, handles: list[str]) -> list[str]:
    """Product ids for storefront handles, preserving order (a thin wrapper over _products_for_handles)."""
    return [str(p["id"]) for p in _products_for_handles(shop, handles) if p.get("id")]


@dataclass
class ExtAuth:
    """Who is calling an extension/keyboard endpoint: always a shop, and a seat when the caller signed
    in with a per-employee seat token (None for the legacy shared per-shop token)."""
    shop: str
    seat_id: Optional[str] = None
    seat_name: Optional[str] = None


def _resolve_ext(x_halia_ext_token: Optional[str]) -> ExtAuth:
    """Authenticate an extension/keyboard request. Prefers a per-employee seat token (refreshing its
    last-seen), then falls back to the legacy shared per-shop token (seat stays None). Raises 401."""
    token_hash = hash_token(x_halia_ext_token) if x_halia_ext_token else ""
    if token_hash:
        seat = shop_store().seat_for_token(token_hash)
        if seat:
            shop_store().touch_seat(seat["seat_id"])
            return ExtAuth(shop=seat["shop"], seat_id=seat["seat_id"], seat_name=seat["name"])
        shop = shop_store().shop_for_extension_token(token_hash)
        if shop:
            return ExtAuth(shop=shop)
    raise HTTPException(401, "Invalid or missing extension token")


def _seat_profile(auth: "ExtAuth") -> dict:
    """{name, email, title, signoff} for the caller's seat; a shared-token caller gets the store
    sender only. The sign-off defaults to name + position + store when the associate set none."""
    from halia.api.settings import settings_for
    s = settings_for(auth.shop)
    store_name = str(dict(shop_store().get_tenant(auth.shop) or {}).get("label") or "").strip()
    prof = shop_store().seat_profile(auth.seat_id) if auth.seat_id else None
    if not prof:
        return {"name": auth.seat_name or "", "email": "", "title": "",
                "signoff": (s.get("sender_name") or "").strip(), "default_signoff": True}
    name = (prof.get("name") or "").strip()
    title = (prof.get("title") or "").strip()
    custom = (prof.get("signoff") or "").strip()
    default = name + (f"\n{title}" if title else "") + (f", {store_name}" if store_name and title else
                                                         (f"\n{store_name}" if store_name else ""))
    return {"name": name, "email": (prof.get("email") or ""), "title": title,
            "signoff": custom or default, "default_signoff": not custom}


def _best(rows: list, pred) -> Optional[dict]:
    best = None
    for r in rows:
        if pred(r) and (best is None or (r.get("score") or 0) > (best.get("score") or 0)):
            best = r
    return best


def _row_match(entry: Optional[dict], email: Optional[str], cid: Optional[str],
               phone: Optional[str] = None, name: Optional[str] = None) -> Optional[dict]:
    """Find a customer in the warm payload by id, email, phone, then (last resort) exact name."""
    rows = ((entry or {}).get("payload") or {}).get("data") or []
    if cid:
        num = str(cid).rsplit("/", 1)[-1]
        forms = {str(cid), num, f"gid://shopify/Customer/{num}"}
        for r in rows:
            if str(r.get("cid")) in forms:
                return r
    if email:
        el = email.lower()
        hit = _best(rows, lambda r: (r.get("email") or "").lower() == el)
        if hit:
            return hit
    if phone:
        pd = _digits(phone)
        if len(pd) >= 7:
            hit = _best(rows, lambda r: _digits(r.get("phone")) == pd)
            if hit:
                return hit
    if name:
        nl = name.strip().lower()
        if nl:
            return _best(rows, lambda r: (r.get("name") or "").strip().lower() == nl)
    return None


def _lookup(shop: str, email: Optional[str], cid: Optional[str],
            phone: Optional[str] = None, name: Optional[str] = None) -> dict:
    from halia.api.app import _pos_live
    from halia.cache import cache

    entry = cache.get(shop)                     # warm path first — never blocks on a sync
    row = _row_match(entry, email, cid, phone, name)
    if row is None and entry is None:           # cold cache: sync once, then match warm
        entry = data.results_for(shop)
        row = _row_match(entry, email, cid, phone, name)
    if row is not None:
        return _resp_from_row(shop, row)
    # Not a flagged client in the book. On a Shopify tenant, score just this one customer live by
    # id or email — they may be new since the last sync. Only surface a genuine hidden VIC.
    r = _pos_live(shop, cid, email) if (cid or email) else None
    if r is not None and getattr(r, "matched", True) and (r.hidden_vic or r.is_priority):
        return _resp_from_result(shop, r)
    return {"found": False}


# ── message drafting ("Draft with Halia") ────────────────────────────────────────────
_DRAFT_SYSTEM = (
    "You are a clienteling assistant for a luxury retailer, writing the sales associate's next "
    "message to a client. Write one short, warm, genuinely personal message the associate can send "
    "as is or lightly edit. Match the client's standing and history: a proven client of long "
    "standing is greeted differently from a first-time buyer. Be specific and concrete; never "
    "generic filler. Plain text only: no markdown, no emoji unless the thread already uses them. "
    "Do not invent facts you were not given (no fake order numbers, dates, prices or product "
    "names). Leave no placeholders such as [name]. Do not use em dashes; use commas, colons or "
    "periods. Return only the message itself, with no preamble or surrounding quotes. Add a "
    "sign-off only if a sender name is provided."
)


def _clean_thread(raw: Any) -> list[dict]:
    """The last few turns of the on-screen conversation, normalised. Capped hard, both to bound
    LLM cost and to keep the model focused on the live exchange. Read in-flight, never stored."""
    out: list[dict] = []
    if isinstance(raw, list):
        for m in raw[-10:]:
            if not isinstance(m, dict):
                continue
            who = "them" if str(m.get("from") or "").lower().startswith(("them", "client", "cust")) \
                else "me"
            txt = str(m.get("text") or "").strip().replace("\r", "")[:800]
            if txt:
                out.append({"from": who, "text": txt})
    return out[-6:]


def _standing(resp: dict) -> str:
    if resp.get("play") == "sleeping":
        return "a proven client who has gone quiet, worth a personal touch to bring them back"
    if resp.get("hidden"):
        return "a hidden high-value client, quietly important though they may not look a VIP on the surface"
    if str(resp.get("tier") or "").startswith("A"):
        return "a top-grade client"
    return "a client"


def _draft_context(shop: str, resp: dict, channel: str, thread: list[dict], instruction: str,
                   closing: str = "\nDraft the associate's next message now.",
                   writer: dict | None = None) -> str:
    """Assemble the user prompt: the client's live standing plus the visible conversation.
    ``closing`` is the instruction that ends the prompt; the brief passes its own."""
    from halia.api.settings import settings_for
    s = settings_for(shop)
    sender = (s.get("sender_name") or "").strip()
    brand = (s.get("brand") or "").strip()
    lines: list[str] = []
    # What this merchant actually offers, and how they sound. Bounds what may be promised: a reply
    # that offers a service they do not run is a promise the associate has to walk back.
    from halia import vip
    house = vip.house_block(s.get("vip_profile"))
    if house:
        lines.append(house + "\n")
    voice = vip.tone_line(s.get("vip_profile"))
    if voice:
        lines.append(voice)
    from halia.voice import voice_brief
    lines.append(voice_brief(s.get("voice")))
    if channel:
        lines.append(f"Channel: {channel}")
    if brand and brand.lower() != "halia":
        lines.append(f"Boutique / brand: {brand}")
    if writer and (writer.get("name") or writer.get("signoff")):
        who = writer.get("name") or sender
        if writer.get("title"):
            who += f", {writer['title']}"
        lines.append(f"You are writing as: {who}")
        if writer.get("signoff"):
            lines.append("Sign off exactly as:\n" + writer["signoff"])
    elif sender:
        lines.append(f"You are writing as: {sender}")
    if resp.get("found"):
        lines.append(f"Client: {resp.get('name') or 'the client'}")
        if resp.get("grade"):
            lines.append(f"Halia grade {resp['grade']}: {_standing(resp)}")
        if resp.get("ordersCount"):
            lines.append(f"Orders to date: {resp['ordersCount']}")
        if resp.get("last"):
            lines.append(f"Most recent order: {resp['last']}")
        if resp.get("latent"):
            lines.append(f"Estimated latent value: {resp['latent']}")
        reasons = [r for r in (resp.get("reasons") or []) if r][:6]
        if reasons:
            lines.append("Why they quietly matter: " + "; ".join(reasons))
        gesture = resp.get("action") or resp.get("reco")
        if gesture:
            lines.append(f"Suggested gesture: {gesture}")
    else:
        lines.append("This person is not a flagged client in the book. Write a warm, professional "
                     "message from the conversation itself.")
    if thread:
        lines.append("\nRecent conversation (oldest first):")
        for m in thread:
            lines.append(("Client: " if m["from"] == "them" else "You: ") + m["text"])
    if instruction:
        lines.append(f"\nWhat you want to say (your intent): {instruction}")
    if closing:
        lines.append(closing)
    return "\n".join(lines)


def _suggest_templates(shop: str, resp: dict, templates: list[dict], limit: int = 3) -> list[str]:
    """The three templates most likely right for THIS client, by name, so the associate never
    scrolls: birthday soon, an open basket, gone quiet, a first order, a live season moment, then
    the top-client staples. Purely a ranking over the merchant's own templates."""
    names = [t.get("name") or "" for t in templates]
    def find(pred):
        for t in templates:
            if pred((t.get("name") or "").lower(), (t.get("category") or "").lower()):
                return t.get("name")
        return None
    picks: list[str] = []
    def add(n):
        if n and n not in picks and len(picks) < limit:
            picks.append(n)
    cid = str(resp.get("cid") or "")
    if cid:
        try:
            from halia.api.birthdays import upcoming
            if any(str(b.get("cid")) == cid.rsplit("/", 1)[-1] for b in upcoming(shop, 7)):
                add(find(lambda n, c: "birthday" in n))
        except Exception:  # noqa: BLE001
            pass
    if (resp.get("cart") or {}).get("count"):
        add(find(lambda n, c: "set aside" in n or "basket" in n or "checkout" in n))
    play = resp.get("play") or ""
    if play == "sleeping":
        add(find(lambda n, c: "win" in c or "win-back" in n or "missed" in n))
    if not resp.get("found") or play == "fresh" or (resp.get("ordersCount") or 0) <= 1:
        add(find(lambda n, c: "welcome" in c))
    camp = _running_campaign(shop)
    if camp:
        cname = (camp.get("name") or "").lower()
        add(find(lambda n, c: c == "season" and (n in cname or cname in n)))
    if (resp.get("grade") or "") in ("A*", "A"):
        add(find(lambda n, c: "appointment" in c))
    add(find(lambda n, c: "preview" in c or "arrival" in c))
    add(find(lambda n, c: c == "season"))
    return [n for n in picks if n in names]


def _fallback_draft(shop: str, resp: dict) -> str:
    """A draft when AI is off or unavailable: the merchant's own best-matching template, filled for
    this client. Play-aware (gone quiet -> a win-back template, fresh -> a welcome). Always returns
    something usable, so the button never comes back empty."""
    first = ((resp.get("name") or "").split(" ")[0]) if resp.get("found") else ""
    templates = resp.get("templates") or _templates(shop, first or None)
    want = {"sleeping": "win", "fresh": "welcome"}.get(resp.get("play") or "", "")
    pick = None
    if want:
        for t in templates:
            if want in (t.get("category") or "").lower():
                pick = t
                break
    if pick is None and templates:
        pick = templates[0]
    body = ((pick or {}).get("body") or "").replace("{first_name}", first or "there").strip()
    if body:
        return body
    return f"Hi {first or 'there'}, just checking in from our side. Is there anything I can help you with?"


# ── the conversation brief (read the thread, recommend a reply and the next moves) ───
_BRIEF_SYSTEM = (
    "You are the clienteling desk behind a luxury retailer's sales associate. You are given one "
    "client's standing (how valuable they quietly are, why, and how the relationship is going) and "
    "the conversation currently on the associate's screen. Produce a brief that lets the associate "
    "act in seconds.\n\n"
    "summary: two sentences at most. Where this relationship stands and what the client wants right "
    "now. Lead with what changed or what they are asking for, not with a restatement of their grade. "
    "If the conversation shows an unanswered question, an unresolved problem, or a buying signal, say "
    "so plainly.\n\n"
    "reply: the associate's next message, ready to send or lightly edit. Short, warm, specific to "
    "this person and this conversation. Match the register to their standing: a proven client of long "
    "standing is greeted differently from a first-time buyer. Answer what they actually asked. Plain "
    "text only, no markdown, no emoji unless the thread already uses them. Never invent facts you were "
    "not given: no order numbers, dates, prices, stock levels or product names that do not appear in "
    "the context. Leave no placeholders. Do not use em dashes; use commas, colons or periods. Add a "
    "sign-off only if a sender name is given.\n\n"
    "actions: up to four concrete next moves, most useful first, each with a short label and a one "
    "line reason. Only suggest an action the context actually supports. Use kind 'advice' for "
    "anything that is not one of the wired actions.\n\n"
    "urgency: how soon the associate should act."
)

_BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "reply": {"type": "string"},
        "urgency": {"type": "string", "enum": ["now", "today", "this week", "no rush"]},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string",
                             "enum": ["pipeline", "campaign", "contacted", "catalogue", "note",
                                      "advice"]},
                    "label": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["kind", "label", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "reply", "urgency", "actions"],
    "additionalProperties": False,
}


def _running_campaign(shop: str) -> Optional[dict]:
    """The campaign running today, if any, so the brief can suggest adding this client to it."""
    import json
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    for row in shop_store().list_campaigns(shop):
        starts, ends = row.get("starts") or "", row.get("ends") or ""
        if starts and ends and starts <= today <= ends:
            try:
                cfg = json.loads(row.get("config_json") or "{}")
            except (TypeError, ValueError):
                cfg = {}
            return {"id": row["id"], "name": row["name"],
                    "members": len(cfg.get("members") or [])}
    return None


def _summary_of(resp: dict, last_contact: Optional[dict]) -> str:
    """A factual standing line, built from the scored book. The no-AI version of the brief's
    summary: no inference, just what is true about this client right now."""
    if not resp.get("found"):
        return "Not a flagged client in your book. Reply on the merits of the conversation."
    name = resp.get("name") or "This client"
    bits = [f"{name}, grade {resp.get('grade')}" if resp.get("grade") else name]
    play = resp.get("play")
    if play == "sleeping":
        bits.append("a proven client who has gone quiet")
    elif resp.get("hidden"):
        bits.append("a hidden high-value client")
    n = resp.get("ordersCount")
    if n:
        bits.append(f"{n} order{'s' if n != 1 else ''}" + (f", last {resp['last']}" if resp.get("last") else ""))
    if (resp.get("cart") or {}).get("value"):
        bits.append("has a basket open")
    if last_contact and last_contact.get("by"):
        bits.append(f"already contacted by {last_contact['by']}")
    return ". ".join(bits) + "."


def _suggested_actions(resp: dict, campaign: Optional[dict],
                       last_contact: Optional[dict]) -> list[dict]:
    """Next moves derived from the client's own standing. The no-AI version of the brief's
    actions, and the safety net when a model call fails."""
    out: list[dict] = []
    if not resp.get("found"):
        return out
    if resp.get("play") == "sleeping":
        out.append({"kind": "pipeline", "label": "Add to your outreach list",
                    "why": "A proven client who has gone quiet is worth a personal approach."})
    if (resp.get("cart") or {}).get("value"):
        out.append({"kind": "advice", "label": "Mention their open basket",
                    "why": "They left items in a basket, so the intent is already there."})
    if campaign:
        out.append({"kind": "campaign", "label": f"Add to {campaign['name']}",
                    "why": "A campaign is running now and they fit it."})
    if not last_contact:
        out.append({"kind": "contacted", "label": "Log that you reached out",
                    "why": "Keeps the team in step so nobody messages twice."})
    return out[:4]


def _brief_context(shop: str, resp: dict, channel: str, thread: list[dict], instruction: str,
                   campaign: Optional[dict], last_contact: Optional[dict], writer: dict | None = None) -> str:
    """The user prompt for the brief: the client's live standing plus the visible conversation."""
    lines = [_draft_context(shop, resp, channel, thread, instruction, closing="", writer=writer)]
    if campaign:
        lines.append(f"Campaign running now: {campaign['name']}")
    if last_contact:
        who = last_contact.get("by") or "a colleague"
        note = last_contact.get("note")
        lines.append(f"Already contacted by {who}" + (f" ({note})" if note else "")
                     + ". Do not double up on the same message.")
    if not thread:
        lines.append("\nNo conversation is visible on screen. Brief from the client's standing "
                     "alone, and write an opening message rather than a reply.")
    lines.append("\nWrite the brief now.")
    return "\n".join(lines)


# ── suggesting products for one client ───────────────────────────────────────────────
_SUGGEST_SYSTEM = (
    "You choose which pieces a luxury retailer's sales associate should put in front of one "
    "client. You are given that client's standing, what they have bought before, the conversation "
    "on screen if there is one, and a list of the store's products.\n\n"
    "Choose at most six, best first. Prefer something the client has actually asked about, then "
    "what sits naturally beside what they already own, then the range they can plainly afford. "
    "Do not pick six near-identical things; a considered selection beats a category dump.\n\n"
    "Choose ONLY from the product ids given to you. Never invent a product, a price or an id. If "
    "nothing in the list genuinely suits this client, return an empty list, which is a correct and "
    "expected answer.\n\n"
    "For each pick write one short reason the associate could say out loud, grounded in what you "
    "were told: what they asked for, what they already own, or the occasion. Never claim stock, "
    "delivery dates or discounts. Do not use em dashes; use commas, colons or periods."
)

_SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "why": {"type": "string"}},
                "required": ["id", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["picks"],
    "additionalProperties": False,
}

_CORPUS_CAP = 150        # what the model sees: the whole catalogue would be ~30k tokens a call


def _price(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _shortlist(products: list, bought: list, aov: float, cap: int = _CORPUS_CAP) -> list:
    """Narrow the store's products to a shortlist before the model sees any of them.

    This is the cost control, and it is deterministic on purpose: a price band around what the
    client actually spends, and a lean toward the kinds of thing they already buy. The model then
    chooses within a set we have already judged plausible, which is both cheaper and better than
    asking it to rank two thousand items."""
    if len(products) <= cap:
        return products
    words = {w for t in bought for w in re.findall(r"[a-z]{4,}", t.lower())}
    lo, hi = (aov * 0.35, aov * 3.0) if aov > 0 else (0.0, float("inf"))

    def rank(p):
        price = _price(p.get("price"))
        in_band = lo <= price <= hi if price else False
        text = " ".join([p.get("title") or "", p.get("type") or "", p.get("vendor") or "",
                         " ".join(p.get("tags") or [])]).lower()
        affinity = len(words & set(re.findall(r"[a-z]{4,}", text))) if words else 0
        return (-affinity, 0 if in_band else 1, abs(price - aov) if aov else 0)

    return sorted(products, key=rank)[:cap]


def _digest(products: list) -> str:
    """The shortlist as the model sees it: enough to judge suitability, no more."""
    lines = []
    for p in products:
        bits = [f"{p['id']} | {p.get('title') or ''}"]
        if p.get("type"):
            bits.append(str(p["type"]))
        if p.get("vendor"):
            bits.append(str(p["vendor"]))
        if p.get("price"):
            bits.append(f"{p.get('currency') or ''}{p['price']}".strip())
        tags = [t for t in (p.get("tags") or [])][:4]
        if tags:
            bits.append(", ".join(tags))
        lines.append(" · ".join(bits))
    return "\n".join(lines)


def _variant_of(shop: str, title: str) -> Optional[dict]:
    """The cheapest buyable variant for one product title, so a suggestion can reach the cart.

    Only ever called for the handful the associate is actually being shown: the catalogue-wide
    product query deliberately omits variant ids, and paying for them across the whole store to
    make six of them buyable would be the wrong trade."""
    token = get_valid_token(shop)
    if not token or not title:
        return None
    from scoring.shopify_fetch import _run, http_transport
    from scoring.shopify_graphql import PRODUCT_SEARCH_QUERY, product_search_node
    try:
        data_ = _run(http_transport(shop, token), PRODUCT_SEARCH_QUERY,
                     {"q": f'title:"{title}"', "n": 3}, 2)
    except Exception:  # noqa: BLE001 — a suggestion without a variant is still worth showing
        return None
    for node in ((data_.get("products") or {}).get("nodes")) or []:
        p = product_search_node(node)
        if p["title"].strip().lower() == title.strip().lower() and p["variants"]:
            return p["variants"][0]
    return None


def register(app) -> None:

    @app.post("/v1/extension/token")
    def mint_extension_token(shop: str = Depends(require_shop)) -> dict:
        token = new_token()
        shop_store().set_extension_token(shop, hash_token(token))
        base = (config.HALIA_APP_URL or "").rstrip("/")
        # A deep link the iOS keyboard app understands, rendered as a QR so the merchant can connect
        # the app by scanning it with their phone (no typing a token). The raw token only exists here
        # at mint time, so the QR is built now. If the QR library is unavailable, the token still
        # returns and the manual copy path still works.
        connect = f"halia://connect?t={token}&b={base}"
        qr = None
        try:
            import base64
            import io

            import segno
            buf = io.BytesIO()
            segno.make(connect, error="m").save(buf, kind="png", scale=6, border=2)
            qr = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        except Exception:  # noqa: BLE001 — QR is a convenience; never fail the mint over it
            qr = None
        return {"token": token, "base": base, "connect": connect, "qr": qr}

    @app.get("/v1/extension/token")
    def extension_token_status(shop: str = Depends(require_shop)) -> dict:
        return {"enabled": bool(shop_store().get_extension_token_hash(shop)),
                "base": (config.HALIA_APP_URL or "").rstrip("/")}

    @app.post("/v1/extension/signout")
    def extension_signout(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """Device-side sign-out for a seat: mark the seat inactive so it stops counting as an active
        head. The device also clears its stored token locally. A manager 'revoke' is the hard kill."""
        auth = _resolve_ext(x_halia_ext_token)
        if auth.seat_id:
            shop_store().signout_seat(auth.seat_id)
        return {"ok": True}

    @app.get("/v1/extension/birthdays")
    def extension_birthdays(x_halia_ext_token: Optional[str] = Header(None), days: int = 14) -> dict:
        """Birthdays coming up, for the desk: name, date, grade, with the note one tap away."""
        from halia.api.birthdays import upcoming

        auth = _resolve_ext(x_halia_ext_token)
        rows = upcoming(auth.shop, max(1, min(int(days or 14), 90)))
        return {"count": len(rows), "birthdays": rows}

    @app.get("/v1/extension/week")
    def extension_week(x_halia_ext_token: Optional[str] = Header(None), days: int = 7) -> dict:
        """The signed-in associate's own week: contacts, clients, captures, conversions, revenue,
        beside the team's totals. Seat-authed; a shared-token caller has no row."""
        from halia.api.reports import seat_week

        auth = _resolve_ext(x_halia_ext_token)
        if not auth.seat_id:
            return {"available": False, "me": None, "team": {}, "days": days}
        return seat_week(auth.shop, auth.seat_id, max(1, min(int(days or 365), 365)))

    @app.get("/v1/extension/profile")
    def extension_profile(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """The signed-in associate's own details (name, email, position, sign-off)."""
        auth = _resolve_ext(x_halia_ext_token)
        return {"profile": _seat_profile(auth), "seat": bool(auth.seat_id)}

    @app.post("/v1/extension/profile")
    def extension_profile_save(x_halia_ext_token: Optional[str] = Header(None),
                               payload: Any = Body(default=None)) -> dict:
        """Update the signed-in associate's details from the extension or the iPhone app. The
        email stays unique per shop; the sign-off is what drafts and templates sign with."""
        from halia.capture_quality import clean_email

        auth = _resolve_ext(x_halia_ext_token)
        if not auth.seat_id:
            raise HTTPException(400, "Sign in with your own seat to set your details.")
        body = payload or {}
        fields: dict = {}
        for key in ("name", "title", "signoff"):
            if key in body:
                fields[key] = str(body.get(key) or "")
        if "email" in body:
            raw = str(body.get("email") or "").strip()
            if raw:
                email, _, ok = clean_email(raw, check_dns=False)
                if not ok:
                    raise HTTPException(422, "That email address does not look right.")
                other = shop_store().seat_by_email(auth.shop, email)
                if other and other["id"] != auth.seat_id:
                    raise HTTPException(409, "A teammate already uses that email.")
                fields["email"] = email
            else:
                fields["email"] = ""
        shop_store().update_seat_profile(auth.seat_id, **fields)
        return {"ok": True, "profile": _seat_profile(auth)}

    @app.get("/v1/extension/context")
    def extension_context(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """The toolbar's standing context, independent of any one client: the merchant's templates,
        their live catalogue, and the campaigns running now. Refreshed by the extension so the
        toolbar is always ready. No customer data."""
        import json
        from datetime import date, timezone, datetime

        from halia.api.campaigns import _utm_slug
        from halia.api.settings import settings_for

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        s = settings_for(shop)
        catalog = _catalog_link(shop)
        today = datetime.now(timezone.utc).date().isoformat()
        campaigns = []
        for row in shop_store().list_campaigns(shop):
            try:
                cfg = json.loads(row.get("config_json") or "{}")
            except (TypeError, ValueError):
                cfg = {}
            starts, ends = row.get("starts") or "", row.get("ends") or ""
            campaigns.append({
                "id": row["id"], "name": row["name"], "starts": starts, "ends": ends,
                "running": bool(starts <= today <= ends) if (starts and ends) else False,
                "members": len((cfg.get("members") or [])),
                "utm": (cfg.get("utm") or {}).get("campaign") or _utm_slug(row["name"]) or row["id"],
            })
        campaigns.sort(key=lambda c: (not c["running"], c["starts"] or ""))
        tenant = dict(shop_store().get_tenant(shop) or {})
        return {
            "label": tenant.get("label") or shop,
            "platform": tenant.get("kind") or ("shopify" if shop.endswith(".myshopify.com") else "shopify"),
            "brand": s.get("brand") or "halia",
            "catalog": catalog,
            "dashboard": _dashboard_link(),
            "templates": _templates(shop, None, catalog, sender=_seat_profile(auth).get("signoff")),
            "profile": _seat_profile(auth),
            "suggested": _suggest_templates(shop, {"found": False, "ordersCount": 0},
                                            _templates(shop, None, catalog)),
            "campaigns": campaigns,
            "todos": _todos(shop),
            "seat": auth.seat_name,                       # who is signed in (None on the legacy token)
            "slack": bool(shop_store().get_slack(shop)),   # team broadcasts available?
        }

    @app.post("/v1/extension/lookup")
    def extension_lookup(x_halia_ext_token: Optional[str] = Header(None),
                         payload: Any = Body(default=None)) -> dict:
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        email = (str(body.get("email") or "").strip()) or None
        cid = (str(body.get("cid") or body.get("customer_id") or "").strip()) or None
        phone = (str(body.get("phone") or "").strip()) or None
        name = (str(body.get("name") or "").strip()) or None
        if not (email or cid or phone or name):
            raise HTTPException(422, "Provide email, cid, phone or name")
        data.record_activity(shop, "extension_lookup")
        return _lookup(shop, email, cid, phone, name)

    @app.post("/v1/extension/draft")
    def extension_draft(x_halia_ext_token: Optional[str] = Header(None),
                        payload: Any = Body(default=None)) -> dict:
        """Draft the associate's next message for the client on screen. Reads the client's live
        grade and reasons (the same warm book as /lookup) plus the visible thread the associate is
        already looking at, and returns a ready-to-edit reply. Falls back to the merchant's own
        template when no AI key is configured, when the per-week cost cap is reached, or when a
        draft can't be produced, so the button always returns something. Zero-retention: the client
        context and thread are used in-flight and discarded; nothing about the customer is stored."""
        from halia import llm

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        email = (str(body.get("email") or "").strip()) or None
        cid = (str(body.get("cid") or body.get("customer_id") or "").strip()) or None
        phone = (str(body.get("phone") or "").strip()) or None
        name = (str(body.get("name") or "").strip()) or None
        channel = str(body.get("channel") or "").strip()[:24]
        instruction = str(body.get("instruction") or "").strip()[:500]
        thread = _clean_thread(body.get("thread"))

        resp = _lookup(shop, email, cid, phone, name) if (email or cid or phone or name) \
            else {"found": False}

        draft, source, model = None, "template", None
        cap = config.LLM_WEEKLY_CAP
        used = shop_store().shop_metric(shop, "extension_draft_ai") if cap else 0
        if llm.available() and (not cap or used < cap):
            model = llm.model_for(resp.get("tier"))
            text = llm.complete(_DRAFT_SYSTEM, _draft_context(shop, resp, channel, thread, instruction,
                                                              writer=_seat_profile(auth)),
                                model=model, max_tokens=600)
            if text:
                draft, source = text, "ai"
                data.record_activity(shop, "extension_draft_ai")
        if draft is None:
            draft, model = _fallback_draft(shop, resp), None
        data.record_activity(shop, "extension_draft")
        return {"draft": draft, "source": source, "model": model,
                "found": bool(resp.get("found")), "name": resp.get("name"),
                "grade": resp.get("grade"), "ai_available": llm.available()}

    @app.post("/v1/extension/brief")
    def extension_brief(x_halia_ext_token: Optional[str] = Header(None),
                        payload: Any = Body(default=None)) -> dict:
        """Read the conversation on screen and brief the associate: where the relationship stands,
        a ready-to-send reply, and the next moves worth making. One model call returns all three,
        constrained to a schema so the shape is guaranteed.

        Works without AI: with no key configured, past the weekly cap, or on any model failure, the
        summary comes from the scored book, the actions from the client's own standing, and the
        reply from the merchant's best-matching template. Zero-retention: the standing and the
        thread are used in-flight and discarded; nothing about the customer is stored."""
        from halia import llm

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        email = (str(body.get("email") or "").strip()) or None
        cid = (str(body.get("cid") or body.get("customer_id") or "").strip()) or None
        phone = (str(body.get("phone") or "").strip()) or None
        name = (str(body.get("name") or "").strip()) or None
        channel = str(body.get("channel") or "").strip()[:24]
        instruction = str(body.get("instruction") or "").strip()[:500]
        thread = _clean_thread(body.get("thread"))

        resp = _lookup(shop, email, cid, phone, name) if (email or cid or phone or name) \
            else {"found": False}
        campaign = _running_campaign(shop)
        last_contact = None
        if resp.get("cid"):
            try:
                from halia.api.board import _sink, load_pipe
                last_contact = _last_outreach(load_pipe(
                    _sink(shop).get_metafield(resp["cid"], "pipeline")).get("activity"))
            except Exception:      # noqa: BLE001 — non-Shopify tenant, or no metafield yet
                last_contact = None

        out, source = None, "book"
        cap = config.LLM_WEEKLY_CAP
        used = shop_store().shop_metric(shop, "extension_brief_ai") if cap else 0
        if llm.available() and (not cap or used < cap):
            got = llm.structured(
                _BRIEF_SYSTEM,
                _brief_context(shop, resp, channel, thread, instruction, campaign, last_contact, writer=_seat_profile(auth)),
                _BRIEF_SCHEMA, model=llm.model_for(resp.get("tier")))
            if got and got.get("reply"):
                out, source = got, "ai"
                data.record_activity(shop, "extension_brief_ai")
        if out is None:                       # no key, past the cap, or the call failed
            out = {"summary": _summary_of(resp, last_contact),
                   "reply": _fallback_draft(shop, resp),
                   "urgency": "today" if resp.get("play") == "sleeping" else "no rush",
                   "actions": _suggested_actions(resp, campaign, last_contact)}
        data.record_activity(shop, "extension_brief")
        return {
            "summary": out.get("summary") or "",
            "reply": out.get("reply") or "",
            "urgency": out.get("urgency") or "",
            "actions": [a for a in (out.get("actions") or []) if a.get("label")][:4],
            "source": source,
            "found": bool(resp.get("found")),
            "name": resp.get("name"),
            "grade": resp.get("grade"),
            "cid": resp.get("cid"),
            "campaign": campaign,             # so the toolbar can wire the "add to campaign" action
            "read_thread": len(thread),       # how many messages the brief actually saw
            "ai_available": llm.available(),
        }

    @app.post("/v1/extension/suggest")
    def extension_suggest(x_halia_ext_token: Optional[str] = Header(None),
                          payload: Any = Body(default=None)) -> dict:
        """Which pieces to put in front of this client, chosen from the merchant's own products.

        The model only ever picks ids out of a shortlist the server built from Shopify, and every
        id it returns is checked back against that shortlist, so it cannot invent a product, a
        price or a link. With no model available it returns nothing rather than a guess: the manual
        product search beside it is untouched. Zero-retention holds — the client's standing and the
        conversation are used in-flight and discarded."""
        from halia import llm
        from halia.api import catalog
        from halia.api.data import bought_titles
        from halia.cache import cache

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        email = (str(body.get("email") or "").strip()) or None
        cid = (str(body.get("cid") or "").strip()) or None
        phone = (str(body.get("phone") or "").strip()) or None
        name = (str(body.get("name") or "").strip()) or None
        instruction = str(body.get("instruction") or "").strip()[:300]
        thread = _clean_thread(body.get("thread"))

        cap = config.LLM_WEEKLY_CAP
        used = shop_store().shop_metric(shop, "extension_suggest_ai") if cap else 0
        if not llm.available() or (cap and used >= cap):
            return {"picks": [], "source": "none", "ai_available": llm.available()}

        resp = _lookup(shop, email, cid, phone, name) if (email or cid or phone or name) \
            else {"found": False}
        row = _row_match(cache.get(shop), email, cid, phone, name) or {}
        bought = bought_titles(row.get("orders"))
        n_orders = row.get("ordersCount") or 0
        aov = (_price(row.get("spend")) / n_orders) if n_orders else 0.0

        try:
            products = catalog._products(shop)
        except Exception:  # noqa: BLE001 — no products, no suggestions; never a broken panel
            products = []
        if not products:
            return {"picks": [], "source": "none", "ai_available": True}
        short = _shortlist(products, bought, aov)
        by_id = {str(p["id"]): p for p in short}

        from halia import vip
        from halia.api.settings import settings_for
        house = vip.house_block(settings_for(shop).get("vip_profile"))
        lines = [house + "\n"] if house else []
        lines.append(f"Client: {resp.get('name') or 'this client'}")
        if resp.get("grade"):
            lines.append(f"Halia grade {resp['grade']}: {_standing(resp)}")
        if aov:
            lines.append(f"Typical order: {round(aov)}")
        if bought:
            lines.append("Has bought: " + "; ".join(bought))
        reasons = [s.get("d") for s in (row.get("signals") or []) if s.get("d")][:5]
        if reasons:
            lines.append("Why they matter: " + "; ".join(reasons))
        if thread:
            lines.append("\nConversation on screen (oldest first):")
            lines += [("Client: " if m["from"] == "them" else "You: ") + m["text"] for m in thread]
        if instruction:
            lines.append(f"\nWhat the associate is looking for: {instruction}")
        lines.append("\nProducts to choose from (id | title · type · vendor · price · tags):")
        lines.append(_digest(short))
        lines.append("\nChoose now.")

        got = llm.structured(_SUGGEST_SYSTEM, "\n".join(lines), _SUGGEST_SCHEMA,
                             model=llm.model_for(row.get("tier")), max_tokens=900)
        picks = []
        for p in ((got or {}).get("picks") or [])[:6]:
            prod = by_id.get(str(p.get("id") or ""))
            if not prod:
                continue                        # not one of ours: drop it rather than show it
            variant = _variant_of(shop, prod.get("title") or "")
            picks.append({
                "product_id": str(prod["id"]), "title": prod.get("title") or "",
                "image": prod.get("image_url"), "price": prod.get("price"),
                "currency": prod.get("currency"),
                "variant_id": (variant or {}).get("id"),
                "why": str(p.get("why") or "")[:200],
            })
        if picks:
            data.record_activity(shop, "extension_suggest_ai")
        data.record_activity(shop, "extension_suggest")
        return {"picks": picks, "source": "ai" if picks else "none", "considered": len(short),
                "ai_available": True}

    @app.post("/v1/extension/catalogue")
    def extension_catalogue(x_halia_ext_token: Optional[str] = Header(None),
                            payload: Any = Body(default=None)) -> dict:
        """Mint a shareable link for the selection the associate has built, addressed to this
        client. Nothing is stored: the products travel in the signed link and the name travels in
        it too, exactly as every other personalised catalogue link already works."""
        from halia.api.catalog import adhoc_url

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        ids = [str(p).strip() for p in (body.get("product_ids") or []) if str(p).strip()][:40]
        if not ids:
            raise HTTPException(422, "product_ids is required")
        first = (str(body.get("name") or "").strip().split(" ") or [""])[0][:80]
        data.record_activity(shop, "extension_catalogue")
        return {"url": adhoc_url(shop, ids, first)}

    @app.post("/v1/extension/cart_link")
    def extension_cart_link(x_halia_ext_token: Optional[str] = Header(None),
                            payload: Any = Body(default=None)) -> dict:
        """A Shopify cart permalink for the selected pieces, so the client can pay in the chat.

        READ-ONLY and no new scope: it resolves each product to a buyable variant and builds a
        /cart/<variant>:<qty> link on the merchant's own domain. It creates nothing on the store
        (that is the write-scope 'pay-by-link' tier, kept separate on purpose). Products with no
        buyable variant are skipped. Zero-retention: the selection is used in-flight only."""
        from halia.api import catalog

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        ids = [str(p).strip() for p in (body.get("product_ids") or []) if str(p).strip()][:20]
        if not ids:
            raise HTTPException(422, "product_ids is required")
        try:
            products = catalog._products(shop)
        except Exception:  # noqa: BLE001 — no products, no link; never a broken panel
            products = []
        by_id = {str(p.get("id")): p for p in products}
        from halia.api.catalog import _with_utm
        woo = _woo_store(shop)
        if woo:
            chosen = [(pid, 1) for pid in ids if str(pid) in by_id] or [(pid, 1) for pid in ids]
            url, needs_helper = woo_cart_url(woo, chosen)
            data.record_activity(shop, "extension_cart_link")
            return {"url": _with_utm(url, "halia-cart"), "needs_helper": needs_helper}
        parts = []
        for pid in ids:
            prod = by_id.get(str(pid))
            if not prod:
                continue
            variant = _variant_of(shop, prod.get("title") or "")
            vid = (variant or {}).get("id")
            if vid:
                parts.append(f"{vid}:1")
        if not parts:
            raise HTTPException(422, "No buyable variants for those products")
        data.record_activity(shop, "extension_cart_link")
        return {"url": _with_utm(f"{_cart_base(shop)}/cart/{','.join(parts)}", "halia-cart")}

    @app.get("/v1/extension/events")
    def extension_events(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """Recent high-grade order alerts for the proactive radar. Same RAM feed the dashboard's
        live alerts use (populated by the order webhook when a VIC orders). Nothing is stored;
        the extension polls this and fires a desktop notification for events it hasn't seen."""
        from halia.cache import cache
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        events = [{"order_id": a.get("order_id"), "name": a.get("name"), "grade": a.get("grade"),
                   "spend": a.get("spend"), "signals": a.get("signals") or [], "when": a.get("when")}
                  for a in (cache.get_alerts(shop) or [])][-50:]
        return {"events": events}

    @app.get("/v1/extension/history")
    def extension_history(x_halia_ext_token: Optional[str] = Header(None),
                          cid: str = Query("")) -> dict:
        """The client's last outreach from the shared pipeline log, so the toolbar can flag
        'already contacted' before anyone messages again. Shopify only (the log lives in the
        merchant's own customer metafield). Reads live; stores nothing."""
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        cid = (cid or "").strip()
        if not cid:
            return {"last_contact": None}
        try:
            from halia.api.board import _sink, load_pipe
            pipe = load_pipe(_sink(shop).get_metafield(cid, "pipeline"))
        except Exception:
            return {"last_contact": None}            # non-Shopify tenant, or no metafield yet
        return {"last_contact": _last_outreach(pipe.get("activity"))}

    @app.get("/v1/extension/products")
    def extension_products(x_halia_ext_token: Optional[str] = Header(None),
                           q: Optional[str] = Query(None),
                           limit: int = Query(20)) -> dict:
        """Search the merchant's Shopify products (with buyable variant ids) so the toolbar can build
        a cart permalink for a client. Shopify-only; returns the storefront base for the /cart link.
        Products are the merchant's own catalogue, not customer data."""
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        woo = _woo_store(shop)
        if woo:
            # WooCommerce: the catalogue the builder already reads, filtered here. A product is its
            # own "variant" for the cart link (add-to-cart takes the product id).
            from halia.api import catalog
            try:
                prods = catalog._products(shop)
            except Exception:  # noqa: BLE001
                prods = []
            term = (q or "").strip().lower()
            n = max(1, min(int(limit or 20), 30))
            hits = [p for p in prods if not term or term in (p.get("title") or "").lower()
                    or term in (p.get("sku") or "").lower()][:n]
            return {"products": [{"id": str(p.get("id")), "title": p.get("title") or "",
                                  "handle": p.get("handle") or "", "image": p.get("image_url"),
                                  "variants": [{"id": str(p.get("id")), "title": "", "price": p.get("price")}]}
                                 for p in hits],
                    "cart_base": woo}
        token = get_valid_token(shop)
        if not token:                                # non-Shopify or read-only: no cart builder
            return {"products": [], "cart_base": None}
        from scoring.shopify_fetch import _run, http_transport
        from scoring.shopify_graphql import PRODUCT_SEARCH_QUERY, product_search_node
        n = max(1, min(int(limit or 20), 30))
        term = (q or "").strip()[:80]
        try:
            data_ = _run(http_transport(shop, token), PRODUCT_SEARCH_QUERY, {"q": term, "n": n}, 2)
        except Exception:
            return {"products": [], "cart_base": _cart_base(shop)}
        nodes = ((data_.get("products") or {}).get("nodes")) or []
        products = [p for p in (product_search_node(x) for x in nodes) if p["variants"]]
        return {"products": products, "cart_base": _cart_base(shop)}

    @app.post("/v1/extension/batch")
    def extension_batch(x_halia_ext_token: Optional[str] = Header(None),
                        payload: Any = Body(default=None)) -> dict:
        """Grade many customers at once by email, for the inbox-list triage dots. Warm cache only:
        a batch must be cheap, so it never triggers a sync (unknown emails simply return nothing).
        Returns only grade/tier/play per found email. No customer data is stored."""
        from halia.cache import cache

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        emails = [str(e).strip().lower() for e in (body.get("emails") or []) if str(e).strip()][:100]
        names = [str(n).strip().lower() for n in (body.get("names") or []) if str(n).strip()][:100]
        if not emails and not names:
            return {"grades": {}}
        rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []
        by_email: dict = {}
        by_name: dict = {}
        for r in rows:
            sc = r.get("score") or 0
            em = (r.get("email") or "").lower()
            if em and (em not in by_email or sc > (by_email[em].get("score") or 0)):
                by_email[em] = r
            nm = (r.get("name") or "").strip().lower()
            if nm and (nm not in by_name or sc > (by_name[nm].get("score") or 0)):
                by_name[nm] = r

        def _slim(r):
            return {"grade": r.get("grade"), "tier": r.get("tier"),
                    "hidden": not r.get("known"), "play": _play_of(r)}

        out = {}
        for em in set(emails):
            if em in by_email:
                out[em] = _slim(by_email[em])
        for nm in set(names):                      # WhatsApp list matches on the saved contact name
            if nm not in out and nm in by_name:
                out[nm] = _slim(by_name[nm])
        return {"grades": out}

    @app.post("/v1/extension/action")
    def extension_action(x_halia_ext_token: Optional[str] = Header(None),
                         payload: Any = Body(default=None)) -> dict:
        """Take a one-click clienteling action on a client from the toolbar. Both actions preserve
        zero-retention: 'pipeline' writes a stage tag + metafield into the merchant's own Shopify;
        'campaign_add' stores an opaque customer id in the campaign config (as the dashboard does)."""
        import json as _json

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        action = str(body.get("action") or "").strip()
        cid = str(body.get("cid") or "").strip()
        if not cid:
            raise HTTPException(422, "cid is required")

        # The signed-in seat is the authenticated actor; fall back to the client-passed name (legacy).
        who = auth.seat_name or str(body.get("actor") or "").strip()[:80] or "A team member"

        if action == "contacted":
            # Log that this client was reached out to, so the team is in the loop and nobody
            # double-messages. Records to the shared pipeline activity (Shopify) AND broadcasts to
            # the team's Slack if connected. Best-effort on each side; at least one should land.
            reason = str(body.get("reason") or "").strip()[:200]
            client_name = str(body.get("client_name") or "").strip()[:120]
            recorded = False
            try:
                from halia.api.board import _sink, _write_soft, append_activity, load_pipe
                sink = _sink(shop)
                pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
                # The seat id rides the activity log so per-associate reporting can be derived
                # later from the merchant's own metafields (Halia stores nothing itself).
                append_activity(pipe, "contacted", auth.seat_id, who, note=reason or None)
                recorded = not _write_soft(sink, cid, pipe)
            except Exception:
                recorded = False                     # non-Shopify tenant or write hiccup
            slacked = False
            conn = shop_store().get_slack(shop)
            if conn and conn.get("webhook_url"):
                from halia import notify
                txt = f"{who} contacted {client_name or 'a client'}" + (f" — {reason}" if reason else "")
                try:
                    slacked = bool(notify.send_slack(conn["webhook_url"], txt))
                except Exception:
                    slacked = False
            data.record_activity(shop, "extension_contacted")
            return {"ok": True, "recorded": recorded, "slack": slacked}

        if action == "note":
            from halia.api.board import _sink, _write_soft, append_activity, load_pipe
            note = str(body.get("note") or "").strip()
            if not note:
                raise HTTPException(422, "note is required")
            sink = _sink(shop)                       # 400 if not a Shopify write-back tenant
            pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
            append_activity(pipe, "note", None, who, note=note)
            if _write_soft(sink, cid, pipe):
                raise HTTPException(502, "Could not save to Shopify just now. Please try again.")
            data.record_activity(shop, "extension_note")
            return {"ok": True}

        if action == "pipeline":
            from halia.api.board import _sink, _write_soft, append_activity, load_pipe
            from scoring.shopify_pipeline import STAGES, stage_tag
            sink = _sink(shop)                       # 400 if not a Shopify write-back tenant
            stage = "To reach out"
            pipe = load_pipe(sink.get_metafield(cid, "pipeline"))
            pipe["stage"] = stage
            append_activity(pipe, "added", None, who)
            sink.untag_customer(cid, [stage_tag(s) for s in STAGES if s != stage])
            sink.tag_customer(cid, [stage_tag(stage)])
            _write_soft(sink, cid, pipe)
            data.record_activity(shop, "extension_pipeline_add")
            return {"ok": True, "stage": stage}

        if action == "campaign_add":
            from halia.api.campaigns import _clean_config
            campaign_id = str(body.get("campaign_id") or "").strip()
            if not campaign_id:
                raise HTTPException(422, "campaign_id is required")
            row = shop_store().get_campaign(campaign_id, shop)
            if not row:
                raise HTTPException(404, "Campaign not found")
            cfg = _clean_config(_json.loads(row.get("config_json") or "{}"))
            if cid not in cfg["members"]:
                cfg["members"] = cfg["members"] + [cid]
            shop_store().save_campaign(campaign_id, shop, row["name"], row["starts"], row["ends"],
                                       _json.dumps(cfg))
            data.record_activity(shop, "extension_campaign_add")
            return {"ok": True, "count": len(cfg["members"])}

        raise HTTPException(422, "Unknown action")

    @app.get("/v1/extension/today")
    def extension_today(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """The proactive 'who to reach today' queue for the iOS widget, App Intents and Siri:
        new orders from top clients to acknowledge and proven clients gone quiet to win back.
        The same warm-cache to-dos the toolbar uses (RAM only; nothing is stored)."""
        from datetime import datetime, timezone
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        todos = _todos(shop)
        tenant = dict(shop_store().get_tenant(shop) or {})
        return {
            "label": tenant.get("label") or shop,
            "count": len(todos),
            "todos": todos,
            "dashboard": _dashboard_link(),
            "generated": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/v1/extension/directory")
    def extension_directory(x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        """VIP caller-ID for the iOS Call Directory extension: graded clients as phone -> label, so
        a boutique reads 'Amelia Hart · A*' when a top client rings. Built from the warm scored
        book; once loaded the numbers live only on the merchant's device. Nothing is stored here.
        Entries are de-duplicated and sorted ascending by phone number, as CallKit requires."""
        from halia.cache import cache
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []
        seen: set[str] = set()
        entries = []
        for r in rows:
            e164 = _e164(r.get("phone"))
            name = (r.get("name") or "").strip()
            if not e164 or e164 in seen or not name:
                continue
            seen.add(e164)
            grade = str(r.get("grade") or "").strip()
            label = f"{name} · {grade}" if grade else name
            entries.append({"phone": e164, "label": label[:60], "grade": grade})
        entries.sort(key=lambda x: int(x["phone"]))          # CallKit needs ascending numeric order
        return {"count": len(entries), "entries": entries}

    @app.get("/v1/extension/clients")
    def extension_clients(x_halia_ext_token: Optional[str] = Header(None),
                          q: Optional[str] = None) -> dict:
        """The associate's client book, for the Share extension's reverse flow: share a product, then
        pick who to send it to. Names, grades and a number to send to, from the warm scored book,
        best clients first. Optional name search via ?q=. RAM only; nothing is stored."""
        from halia.cache import cache
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []
        ql = (q or "").strip().lower()
        rank = {"A*": 5, "A": 4, "B": 3, "C": 2, "D": 1}
        out = []
        for r in rows:
            name = (r.get("name") or "").strip()
            if not name or (ql and ql not in name.lower()):
                continue
            out.append({
                "cid": r.get("cid"),
                "name": name,
                "grade": str(r.get("grade") or "").strip(),
                "phone": r.get("phone"),
                "email": r.get("email"),
                "latent": r.get("latent"),
            })
        out.sort(key=lambda c: (-rank.get(c["grade"], 0), c["name"].lower()))
        return {"count": len(out), "clients": out[:500]}

    @app.post("/v1/extension/catalogue_from_urls")
    def extension_catalogue_from_urls(x_halia_ext_token: Optional[str] = Header(None),
                                      payload: Any = Body(default=None)) -> dict:
        """Build a catalogue link from storefront product URLs the associate saved while browsing
        (the iOS 'save while you browse' flow). Each …/products/<handle> is resolved to a product in
        the merchant's own store, then the same signed catalogue link the toolbar builds is minted.
        Shopify-only; nothing is stored (the selection travels in the signed link)."""
        from halia.api.catalog import adhoc_url

        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        urls = [str(u) for u in (body.get("urls") or []) if str(u).strip()][:40]
        handles, seen = [], set()
        for u in urls:
            h = _handle_from_url(u)
            if h and h not in seen:
                seen.add(h)
                handles.append(h)
        if not handles:
            raise HTTPException(422, "No product URLs recognised")
        ids = _ids_for_handles(shop, handles)
        if not ids:
            return {"url": "", "resolved": 0, "requested": len(handles)}
        first = ((str(body.get("name") or "").strip().split(" ") or [""])[0])[:80]
        data.record_activity(shop, "extension_catalogue_urls")
        return {"url": adhoc_url(shop, ids, first), "resolved": len(ids), "requested": len(handles)}

    @app.post("/v1/extension/products_from_urls")
    def extension_products_from_urls(x_halia_ext_token: Optional[str] = Header(None),
                                     payload: Any = Body(default=None)) -> dict:
        """Resolve saved storefront product URLs to product cards (title, image, handle, variants) so
        the keyboard's Saved view can show them as a visual grid. Preserves the saved order.
        Shopify-only; the merchant's own catalogue, nothing customer-related, nothing stored."""
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        token = get_valid_token(shop)
        if not token:                                    # non-Shopify / read-only: no product cards
            return {"products": [], "cart_base": None}
        body = payload or {}
        urls = [str(u) for u in (body.get("urls") or []) if str(u).strip()][:40]
        handles, seen = [], set()
        for u in urls:
            h = _handle_from_url(u)
            if h and h not in seen:
                seen.add(h)
                handles.append(h)
        if not handles:
            return {"products": [], "cart_base": _cart_base(shop)}
        return {"products": _products_for_handles(shop, handles), "cart_base": _cart_base(shop)}

    @app.post("/v1/extension/cart_link_from_urls")
    def extension_cart_link_from_urls(x_halia_ext_token: Optional[str] = Header(None),
                                      payload: Any = Body(default=None)) -> dict:
        """A Shopify /cart pay-in-chat link from saved storefront URLs: resolves each product's first
        buyable variant and builds /cart/<variant>:1 on the merchant's own domain. READ-ONLY and no
        new scope, it creates nothing on the store. Products with no buyable variant are skipped;
        nothing is stored (the selection lives in the link)."""
        auth = _resolve_ext(x_halia_ext_token)
        shop = auth.shop
        body = payload or {}
        urls = [str(u) for u in (body.get("urls") or []) if str(u).strip()][:40]
        handles, seen = [], set()
        for u in urls:
            h = _handle_from_url(u)
            if h and h not in seen:
                seen.add(h)
                handles.append(h)
        if not handles:
            raise HTTPException(422, "No product URLs recognised")
        vids = []
        for p in _products_for_handles(shop, handles):
            variants = p.get("variants") or []
            if variants and variants[0].get("id"):
                vids.append(str(variants[0]["id"]))
        if not vids:
            return {"url": "", "resolved": 0, "requested": len(handles)}
        base = _cart_base(shop).rstrip("/")
        url = base + "/cart/" + ",".join(v + ":1" for v in vids[:40])
        data.record_activity(shop, "extension_cart_link_urls")
        from halia.api.catalog import _with_utm
        return {"url": _with_utm(url, "halia-cart"), "resolved": len(vids), "requested": len(handles)}
