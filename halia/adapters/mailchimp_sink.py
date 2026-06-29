"""MailchimpSink — write the Halia score onto Mailchimp audience members (LIVE).

Each scored customer is upserted into a Mailchimp audience by email, setting Halia
**merge fields** (HGRADE, HSCORE, …) and applying Halia **tags** ("Halia A*",
"Halia Hidden VIC", "Halia: <signal>"). Tags are segmentable and can start a Customer
Journey, so a hidden VIC can trigger an automation the moment it is found.

New contacts are added with status ``transactional`` (NOT subscribed), so Halia never
opts anyone into marketing without consent — it only enriches and tags existing contacts.

A Mailchimp key looks like ``<key>-<dc>`` (e.g. ``abc123…-us21``); the ``dc`` suffix picks
the API host. Auth is HTTP Basic (any username + the key). The HTTP call is injectable as
``transport`` so this is unit-testable against a fake Mailchimp with no network.

Docs: https://mailchimp.com/developer/marketing/api/list-members/
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone

from halia.schema import ScoreResult

# (tag, display name, type) — Mailchimp merge-field tags are <=10 chars, UPPERCASE.
MERGE_FIELDS = [
    ("HGRADE", "Halia Grade", "text"),
    ("HSCORE", "Halia Score", "number"),
    ("HTIER", "Halia Tier", "text"),
    ("HVIC", "Halia Hidden VIC", "text"),
    ("HSIGNALS", "Halia Signals", "text"),
    ("HREASONS", "Halia Reasons", "text"),
    ("HSCOREDAT", "Halia Last Scored", "text"),
]


class MailchimpError(RuntimeError):
    """A non-2xx response from the Mailchimp Marketing API."""


def dc_from_key(api_key: str) -> str:
    if not api_key or "-" not in api_key:
        raise MailchimpError("Mailchimp key must look like <key>-<dc> (for example …-us21).")
    return api_key.rsplit("-", 1)[1]


def subscriber_hash(email: str) -> str:
    """Mailchimp identifies a member by the MD5 of the lower-cased email."""
    return hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()


def _http_transport(api_key: str):
    """Real transport: (method, path, body) -> (status, json). Basic auth on the key's dc."""
    import requests

    base = f"https://{dc_from_key(api_key)}.api.mailchimp.com/3.0"

    def _call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        resp = requests.request(method, base + path, auth=("halia", api_key), json=body, timeout=30)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        return resp.status_code, payload

    return _call


def _tags(result: ScoreResult) -> list[str]:
    tags: list[str] = []
    if result.grade and result.grade != "—":
        tags.append(f"Halia {result.grade}")
    if result.hidden_vic:
        tags.append("Halia Hidden VIC")
    for s in (result.signals or [])[:6]:
        tags.append(f"Halia: {s}")
    return tags


def _merge_values(result: ScoreResult, scored_at: str) -> dict:
    return {
        "HGRADE": result.grade or "",
        "HSCORE": result.score or 0,
        "HTIER": result.tier or "",
        "HVIC": "Yes" if result.hidden_vic else "No",
        "HSIGNALS": ", ".join(result.signals or []),
        "HREASONS": result.reasons or "",
        "HSCOREDAT": scored_at,
    }


def list_audiences(api_key: str, transport=None) -> list[dict]:
    """Return the account's audiences as [{id, name}]. For the connect picker."""
    call = transport or _http_transport(api_key)
    status, payload = call("GET", "/lists?count=100&fields=lists.id,lists.name")
    if not (200 <= status < 300):
        raise MailchimpError(f"HTTP {status}: {json.dumps(payload)[:300]}")
    return [{"id": x.get("id"), "name": x.get("name")} for x in (payload.get("lists") or [])]


def create_static_segment(api_key: str, list_id: str, name: str, emails: list[str],
                          transport=None) -> dict:
    """Create a static (saved) segment of the given emails. Returns {id, name}."""
    call = transport or _http_transport(api_key)
    status, payload = call("POST", f"/lists/{list_id}/segments",
                           {"name": name, "static_segment": emails})
    if not (200 <= status < 300):
        raise MailchimpError(f"HTTP {status}: {json.dumps(payload)[:300]}")
    return {"id": payload.get("id"), "name": payload.get("name") or name}


class MailchimpSink:
    name = "mailchimp"

    def __init__(self, api_key: str, list_id: str, transport=None):
        self.api_key = api_key
        self.list_id = list_id
        self._transport = transport

    def _send(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        if self._transport is None:
            self._transport = _http_transport(self.api_key)
        return self._transport(method, path, body)

    def ensure_merge_fields(self) -> None:
        """Create the Halia merge fields on the audience if they are not already present."""
        status, payload = self._send("GET", f"/lists/{self.list_id}/merge-fields?count=100")
        existing = {m.get("tag") for m in (payload.get("merge_fields") or [])} if 200 <= status < 300 else set()
        for tag, name, typ in MERGE_FIELDS:
            if tag not in existing:
                self._send("POST", f"/lists/{self.list_id}/merge-fields",
                           {"tag": tag, "name": name, "type": typ, "required": False, "public": False})

    def push_one(self, result: ScoreResult, scored_at: str | None = None) -> dict:
        if not result.email:
            raise MailchimpError("Member has no email — Mailchimp upserts by email.")
        scored_at = scored_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        h = subscriber_hash(result.email)
        body = {"email_address": result.email, "status_if_new": "transactional",
                "merge_fields": _merge_values(result, scored_at)}
        status, payload = self._send("PUT", f"/lists/{self.list_id}/members/{h}", body)
        if not (200 <= status < 300):
            raise MailchimpError(f"HTTP {status}: {json.dumps(payload)[:400]}")
        tags = _tags(result)
        if tags:
            self._send("POST", f"/lists/{self.list_id}/members/{h}/tags",
                       {"tags": [{"name": t, "status": "active"} for t in tags]})
        return payload

    def push_many(self, results: Iterable[ScoreResult]) -> int:
        scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        n = 0
        for r in results:
            if r.email:
                self.push_one(r, scored_at)
                n += 1
        return n
