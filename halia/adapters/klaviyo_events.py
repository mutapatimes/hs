"""Fire a Klaviyo EVENT so a merchant's flow can email the client (true one-click).

Klaviyo doesn't let you "send one person an email" directly — emails go through flows.
So Halia fires a custom metric event, **"Halia VIC Identified"**, on the client's profile
(carrying their grade/score/reasons). The merchant builds a Flow triggered by that metric
once; after that, clicking "Email this client" in Halia delivers their email.

Uses the Events API (`POST /api/events`, needs `events:write` scope). Injectable transport
for tests.

Docs: https://developers.klaviyo.com/en/reference/create_event
"""
from __future__ import annotations

from halia.adapters.klaviyo_sink import DEFAULT_REVISION, KlaviyoError
from halia.schema import ScoreResult

EVENTS_URL = "https://a.klaviyo.com/api/events"
METRIC = "Halia VIC Identified"


def _event_body(result: ScoreResult) -> dict:
    return {
        "data": {
            "type": "event",
            "attributes": {
                "properties": {
                    "halia_grade": result.grade,
                    "halia_score": result.score,
                    "halia_reasons": result.reasons,
                },
                "metric": {"data": {"type": "metric", "attributes": {"name": METRIC}}},
                "profile": {"data": {"type": "profile", "attributes": {"email": result.email}}},
                "value": result.spend,
            },
        }
    }


def _http_post(url: str, api_key: str, revision: str, body: dict) -> tuple[int, dict]:
    import requests

    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": revision,
        "accept": "application/json",
        "content-type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    try:
        return resp.status_code, (resp.json() if resp.content else {})
    except ValueError:
        return resp.status_code, {"raw": resp.text}


def fire_event(api_key: str, result: ScoreResult, revision: str = DEFAULT_REVISION,
               transport=None) -> None:
    """Fire the 'Halia VIC Identified' event for one client. Raises on non-2xx."""
    if not result.email:
        raise KlaviyoError("Client has no email — can't trigger a Klaviyo flow.")
    status, payload = (transport or _http_post)(EVENTS_URL, api_key, revision, _event_body(result))
    if not (200 <= status < 300):  # 202 = accepted
        import json

        raise KlaviyoError(f"Events API HTTP {status}: {json.dumps(payload)[:300]}")
