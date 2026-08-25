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

from halia.api.shopify_auth import get_valid_token
from halia.engine import engine

CAPTURE_TAG = "halia-captured"


def _gql(shop: str, token: str, query: str, variables: dict) -> dict:
    """One Admin GraphQL call (seam for tests)."""
    from scoring.shopify_fetch import _run, http_transport

    return _run(http_transport(shop, token), query, variables, 2)


_SEARCH = """
query($q: String!) {
  customers(first: 1, query: $q) { nodes { id email phone tags } }
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


def register(app) -> None:
    @app.post("/v1/capture")
    def capture(body: Any = Body(...),
                x_halia_ext_token: Optional[str] = Header(None)) -> dict:
        from halia.api.extension import _resolve_ext

        auth = _resolve_ext(x_halia_ext_token)
        if not isinstance(body, dict):
            raise HTTPException(422, "Body must be a JSON object")

        email = _clean(body.get("email")).lower()
        phone = _clean(body.get("phone"))
        if not email and not phone:
            raise HTTPException(422, "Capture needs at least an email or a phone number")

        token = get_valid_token(auth.shop)
        if not token:
            raise HTTPException(409, "This store has no Shopify connection to save the client into")

        first, last = _clean(body.get("first_name")), _clean(body.get("last_name"))
        channel = _clean(body.get("channel")) or "handover"
        consent = body.get("consent") or {}
        wants_email = bool(consent.get("email_marketing")) and bool(email)
        wants_sms = bool(consent.get("sms_marketing")) and bool(phone)

        existing = _find_existing(auth.shop, token, email, phone)
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
            cust_input["tags"] = [CAPTURE_TAG, f"halia-capture-{channel}"]
            data_ = _gql(auth.shop, token, _CREATE, {"input": cust_input})
            node = (data_ or {}).get("customerCreate") or {}
        else:
            cust_input["id"] = existing["id"]
            # Never clobber an existing email/phone with a duplicate-key error: keep only new ones.
            if _clean(existing.get("email")):
                cust_input.pop("email", None)
            if _clean(existing.get("phone")):
                cust_input.pop("phone", None)
            data_ = _gql(auth.shop, token, _UPDATE, {"input": cust_input})
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
                _gql(auth.shop, token, _TAGS_ADD,
                     {"id": cid, "tags": [CAPTURE_TAG, f"halia-capture-{channel}"]})
            except Exception:  # noqa: BLE001
                pass

        # The consent record + preferences live on the customer, in the merchant's own store.
        now = datetime.now(timezone.utc).isoformat()
        capture_record = {
            "channel": channel, "at": now,
            "associate": auth.seat_name or "", "seat_id": auth.seat_id or "",
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
            _gql(auth.shop, token, _METAFIELDS_SET, {"metafields": metafields})
        except Exception:  # noqa: BLE001
            pass

        # Marketing consent, only where the client opted in — written to Shopify's native
        # consent fields so Klaviyo and every downstream tool respect it.
        if wants_email:
            try:
                _gql(auth.shop, token, _EMAIL_CONSENT, {"input": {
                    "customerId": cid,
                    "emailMarketingConsent": {"marketingState": "SUBSCRIBED",
                                              "marketingOptInLevel": "SINGLE_OPT_IN",
                                              "consentUpdatedAt": now}}})
            except Exception:  # noqa: BLE001
                pass
        if wants_sms:
            try:
                _gql(auth.shop, token, _SMS_CONSENT, {"input": {
                    "customerId": cid,
                    "smsMarketingConsent": {"marketingState": "SUBSCRIBED",
                                            "marketingOptInLevel": "SINGLE_OPT_IN",
                                            "consentUpdatedAt": now}}})
            except Exception:  # noqa: BLE001
                pass

        out = {"ok": True, "created": created, "customer_id": cid}
        out.update(_score_capture(cid, body, email, phone))
        return out
