"""KlaviyoSink — write the Halia score onto a Klaviyo profile (LIVE).

So a marketer can segment campaigns on the grade. Each scored customer is upserted by
email via Klaviyo's **Create or Update Profile** endpoint (`POST /api/profile-import`),
setting custom profile properties:

    halia_grade   <- result.grade      ("A*", "A", "B", "C")
    halia_score   <- result.score      (0–100)
    halia_reasons <- result.reasons
    halia_scored_at <- ISO timestamp

Auth is a Klaviyo **private** API key (`pk_…`, scope `profiles:write`) in
`KLAVIYO_API_KEY`. The HTTP call is injectable as `transport` so it is unit-testable
against a fake Klaviyo with no network.

Quick connection test (pushes ONE profile, prints Klaviyo's response):

    KLAVIYO_API_KEY=pk_xxx python -m halia.adapters.klaviyo_sink you@example.com

Docs: https://developers.klaviyo.com/en/reference/create_or_update_profile
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime, timezone

from halia.ports import ScoreSink
from halia.schema import ScoreResult

API_URL = "https://a.klaviyo.com/api/profile-import"
# Klaviyo pins behaviour to a dated revision; override with KLAVIYO_REVISION if needed.
DEFAULT_REVISION = os.environ.get("KLAVIYO_REVISION", "2026-04-15")

# Custom-property names as they appear in Klaviyo. Title Case (not snake_case) so the
# profile's Custom Properties panel reads cleanly. The grade/hidden-VIC property names
# are reused by the segment builder so segments and profiles always agree.
GRADE_PROPERTY = "Halia Grade"
HIDDEN_VIC_PROPERTY = "Halia Hidden VIC"


class KlaviyoError(RuntimeError):
    """A non-2xx response from the Klaviyo API."""


def _properties(result: ScoreResult, scored_at: str) -> dict:
    """The clean, Title-Case Halia custom properties written onto the profile."""
    return {
        GRADE_PROPERTY: result.grade,
        "Halia Score": result.score,
        "Halia Tier": result.tier,
        "Halia Reasons": result.reasons,
        HIDDEN_VIC_PROPERTY: bool(result.hidden_vic),
        "Halia Last Scored": scored_at,
    }


def _profile_body(result: ScoreResult, scored_at: str) -> dict:
    """The Create-or-Update-Profile payload for one customer (upsert by email)."""
    return {
        "data": {
            "type": "profile",
            "attributes": {
                "email": result.email,
                "properties": _properties(result, scored_at),
            },
        }
    }


def _http_transport(api_key: str, revision: str):
    """Real transport: POST one profile body to Klaviyo, return (status, json)."""
    import requests

    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "revision": revision,
        "accept": "application/json",
        "content-type": "application/json",
    }

    def _call(body: dict) -> tuple[int, dict]:
        resp = requests.post(API_URL, headers=headers, json=body, timeout=30)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        return resp.status_code, payload

    return _call


class KlaviyoSink(ScoreSink):
    name = "klaviyo"

    def __init__(self, api_key: str | None = None, transport=None, revision: str = DEFAULT_REVISION):
        from halia import config
        self.api_key = api_key or config.KLAVIYO_API_KEY
        self.revision = revision
        self._transport = transport  # injectable for tests / dry runs

    def _send(self, body: dict) -> tuple[int, dict]:
        transport = self._transport
        if transport is None:
            if not self.api_key:
                raise KlaviyoError("No Klaviyo API key (set KLAVIYO_API_KEY).")
            transport = self._transport = _http_transport(self.api_key, self.revision)
        return transport(body)

    def push_one(self, result: ScoreResult, scored_at: str | None = None) -> dict:
        """Upsert one profile; return Klaviyo's JSON. Raises on non-2xx."""
        if not result.email:
            raise KlaviyoError("Profile has no email — Klaviyo upserts by email.")
        scored_at = scored_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        status, payload = self._send(_profile_body(result, scored_at))
        if not (200 <= status < 300):
            raise KlaviyoError(f"HTTP {status}: {json.dumps(payload)[:500]}")
        return payload

    def push_many(self, results: Iterable[ScoreResult]) -> None:
        scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in results:
            if r.email:  # skip customers with no email (can't be upserted)
                self.push_one(r, scored_at)


def _demo_result(email: str) -> ScoreResult:
    return ScoreResult(
        matched=True, flagged=True, tier="A1", grade="A*", score=99, is_priority=True,
        signal_count=2, signals=["Work email", "HNWI postcode"],
        reasons="Work email: Goldman Sachs; HNWI postcode: SW1X (Halia connection test)",
        gesture="", spend=420.0, hidden_vic=True, customer_id="halia-test", email=email, phone=None,
    )


def main() -> None:  # pragma: no cover - live connection test, needs a real key
    import sys

    if len(sys.argv) < 2:
        print("usage: KLAVIYO_API_KEY=pk_xxx python -m halia.adapters.klaviyo_sink <email>")
        raise SystemExit(2)
    email = sys.argv[1]
    sink = KlaviyoSink()
    print(f"Pushing a test Halia profile to Klaviyo for {email} (revision {sink.revision}) ...")
    payload = sink.push_one(_demo_result(email))
    print("OK — Klaviyo accepted it. Profile attributes returned:")
    print(json.dumps(payload.get("data", payload), indent=2)[:900])
    print("\nNow check this profile in Klaviyo: it should have custom properties "
          "'Halia Grade'=A*, 'Halia Score'=99, 'Halia Reasons'=…, 'Halia Last Scored'=…")


if __name__ == "__main__":  # pragma: no cover
    main()
