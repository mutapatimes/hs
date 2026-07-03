"""HubSpotSink — write the Halia score onto HubSpot contacts (LIVE).

Each scored customer is upserted into HubSpot by email, setting Halia **contact properties**
(halia_grade, halia_score, halia_tier, halia_vic, halia_signals, halia_reasons, halia_scored_at)
via ``POST /crm/v3/objects/contacts/batch/upsert`` (idProperty=email). First-time setup creates
those custom properties. A CRM/clienteling team then sees the grade on the contact and can build
active lists or workflows off it.

Auth is a **HubSpot Private App token** (Bearer). The HTTP call is injectable as ``transport`` so
this is unit-testable against a fake HubSpot with no network.

Docs: https://developers.hubspot.com/docs/api/crm/contacts
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone

from halia.ports import ScoreSink
from halia.schema import ScoreResult

_BASE = "https://api.hubapi.com"

# (name, label, type, fieldType) — the Halia custom contact properties.
PROPERTIES = [
    ("halia_grade", "Halia Grade", "string", "text"),
    ("halia_score", "Halia Score", "number", "number"),
    ("halia_tier", "Halia Tier", "string", "text"),
    ("halia_vic", "Halia Hidden VIC", "string", "text"),
    ("halia_signals", "Halia Signals", "string", "text"),
    ("halia_reasons", "Halia Reasons", "string", "text"),
    ("halia_scored_at", "Halia Last Scored", "string", "text"),
]


class HubSpotError(RuntimeError):
    """A non-2xx response from the HubSpot CRM API."""


def _http_transport(token: str):
    """Real transport: (method, path, body) -> (status, json). Bearer auth on the private-app token."""
    import requests

    def _call(method: str, path: str, body: object = None) -> tuple[int, dict]:
        resp = requests.request(method, _BASE + path,
                                headers={"Authorization": f"Bearer {token}",
                                         "Content-Type": "application/json"},
                                json=body, timeout=30)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        return resp.status_code, payload

    return _call


def _property_values(result: ScoreResult, scored_at: str) -> dict:
    return {
        "halia_grade": result.grade or "",
        "halia_score": result.score or 0,
        "halia_tier": result.tier or "",
        "halia_vic": "Yes" if result.hidden_vic else "No",
        "halia_signals": ", ".join(result.signals or []),
        "halia_reasons": result.reasons or "",
        "halia_scored_at": scored_at,
    }


def validate_token(token: str, transport=None) -> dict:
    """A cheap authed GET to confirm the private-app token works. Raises on failure."""
    call = transport or _http_transport(token)
    status, payload = call("GET", "/crm/v3/objects/contacts?limit=1")
    if not (200 <= status < 300):
        raise HubSpotError(f"HTTP {status}: {json.dumps(payload)[:300]}")
    return {"ok": True}


def create_static_list(token: str, name: str, contact_ids: list, transport=None) -> dict:
    """Create a HubSpot static (MANUAL) contact list and add the given contact ids to it."""
    call = transport or _http_transport(token)
    status, payload = call("POST", "/crm/v3/lists",
                           {"name": name, "objectTypeId": "0-1", "processingType": "MANUAL"})
    if not (200 <= status < 300):
        raise HubSpotError(f"HTTP {status}: {json.dumps(payload)[:300]}")
    list_id = (payload.get("list") or {}).get("listId") or payload.get("listId")
    ids = [str(c) for c in contact_ids if c]
    if list_id and ids:
        call("PUT", f"/crm/v3/lists/{list_id}/memberships/add", ids)
    return {"id": list_id, "name": name}


class HubSpotSink(ScoreSink):
    name = "hubspot"

    def __init__(self, token: str | None = None, transport=None):
        from halia import config
        self.token = token or config.HUBSPOT_TOKEN
        self._transport = transport

    def _send(self, method: str, path: str, body: object = None) -> tuple[int, dict]:
        if self._transport is None:
            self._transport = _http_transport(self.token)
        return self._transport(method, path, body)

    def ensure_properties(self) -> None:
        """Create the Halia contact properties on the portal if they are not already present."""
        status, payload = self._send("GET", "/crm/v3/properties/contacts")
        existing = {p.get("name") for p in (payload.get("results") or [])} if 200 <= status < 300 else set()
        for name, label, typ, field in PROPERTIES:
            if name not in existing:
                self._send("POST", "/crm/v3/properties/contacts",
                           {"name": name, "label": label, "type": typ, "fieldType": field,
                            "groupName": "contactinformation"})

    def upsert(self, results: Iterable[ScoreResult], scored_at: str | None = None) -> list[dict]:
        """Batch-upsert contacts by email; returns [{email, id}] for the contacts written."""
        scored_at = scored_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        targets = [r for r in results if r.email]
        out: list[dict] = []
        for i in range(0, len(targets), 100):                    # HubSpot batch cap is 100
            chunk = targets[i:i + 100]
            inputs = [{"idProperty": "email", "id": r.email,
                       "properties": _property_values(r, scored_at)} for r in chunk]
            status, payload = self._send("POST", "/crm/v3/objects/contacts/batch/upsert",
                                         {"inputs": inputs})
            if not (200 <= status < 300):
                raise HubSpotError(f"HTTP {status}: {json.dumps(payload)[:400]}")
            for res in (payload.get("results") or []):
                out.append({"email": (res.get("properties") or {}).get("email") or "",
                            "id": res.get("id")})
        return out

    def push_one(self, result: ScoreResult, scored_at: str | None = None) -> dict:
        if not result.email:
            raise HubSpotError("Contact has no email — HubSpot upserts by email.")
        got = self.upsert([result], scored_at)
        return got[0] if got else {}

    def push_many(self, results: Iterable[ScoreResult]) -> int:
        return len(self.upsert(list(results)))
