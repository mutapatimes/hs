"""Create default Halia grade segments in Klaviyo (then edit them freely in the UI).

Halia ships a starter set of segments keyed on the `Halia Grade` profile property it
writes via `klaviyo_sink`:

    Halia · A* — Hidden VICs   (Halia Grade = A*)
    Halia · A                  (Halia Grade = A)
    Halia · B                  (Halia Grade = B)
    Halia · C                  (Halia Grade = C)
    Halia · Priority (A*/A)    (Halia Grade = A*  OR  = A)
    Halia · Hidden VIC         (Halia Hidden VIC = true)

These are ordinary Klaviyo segments — once created, the user opens any of them in
Klaviyo and edits the conditions, name, or list however they like. Creation is
idempotent: a segment whose name already exists is left untouched.

    KLAVIYO_API_KEY=pk_xxx python -m halia.adapters.klaviyo_segments

Needs `segments:read` + `segments:write` scope. Docs:
https://developers.klaviyo.com/en/reference/create_segment
"""
from __future__ import annotations

import json

from halia.adapters.klaviyo_sink import (
    DEFAULT_REVISION, GRADE_PROPERTY, HIDDEN_VIC_PROPERTY, KlaviyoError,
)

LIST_URL = "https://a.klaviyo.com/api/segments"
CREATE_URL = "https://a.klaviyo.com/api/segments"


def _property_condition(name: str, value, vtype: str = "string") -> dict:
    """One 'profile custom property <name> equals <value>' condition.

    Klaviyo requires custom properties to be referenced as ``properties['name']``.
    """
    return {
        "type": "profile-property",
        "property": f"properties['{name}']",
        "filter": {"type": vtype, "operator": "equals", "value": value},
    }


def _definition(conditions: list[dict]) -> dict:
    """Wrap conditions in a single OR-group (conditions in a group are OR'd)."""
    return {"condition_groups": [{"conditions": conditions}]}


def default_segments() -> list[tuple[str, dict]]:
    """(name, definition) for the starter set."""
    grades = [("A*", "A* — Hidden VICs"), ("A", "A"), ("B", "B"), ("C", "C")]
    out = [
        (f"Halia · {label}", _definition([_property_condition(GRADE_PROPERTY, g)]))
        for g, label in grades
    ]
    out.append(("Halia · Priority (A*/A)", _definition(
        [_property_condition(GRADE_PROPERTY, "A*"), _property_condition(GRADE_PROPERTY, "A")]
    )))
    out.append(("Halia · Hidden VIC", _definition(
        [_property_condition(HIDDEN_VIC_PROPERTY, True, vtype="boolean")]
    )))
    return out


def _segment_body(name: str, definition: dict) -> dict:
    return {"data": {"type": "segment",
                     "attributes": {"name": name, "definition": definition}}}


class KlaviyoSegments:
    """Create/list Halia segments. `transport` is injectable for tests."""

    def __init__(self, api_key: str | None = None, transport=None, revision: str = DEFAULT_REVISION):
        from halia import config
        self.api_key = api_key or config.KLAVIYO_API_KEY
        self.revision = revision
        self._transport = transport

    def _http(self):
        import requests

        headers = {
            "Authorization": f"Klaviyo-API-Key {self.api_key}",
            "revision": self.revision,
            "accept": "application/json",
            "content-type": "application/json",
        }

        def _call(method: str, url: str, body: dict | None) -> tuple[int, dict]:
            resp = requests.request(method, url, headers=headers, json=body, timeout=30)
            try:
                payload = resp.json()
            except ValueError:
                payload = {"raw": resp.text}
            return resp.status_code, payload

        return _call

    def _send(self, method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        transport = self._transport
        if transport is None:
            if not self.api_key:
                raise KlaviyoError("No Klaviyo API key (set KLAVIYO_API_KEY).")
            transport = self._transport = self._http()
        return transport(method, url, body)

    def existing_names(self) -> set[str]:
        status, payload = self._send("GET", LIST_URL, None)
        if not (200 <= status < 300):
            raise KlaviyoError(f"list segments HTTP {status}: {json.dumps(payload)[:300]}")
        return {s["attributes"]["name"] for s in payload.get("data", [])}

    def create(self, name: str, definition: dict) -> dict:
        status, payload = self._send("POST", CREATE_URL, _segment_body(name, definition))
        if not (200 <= status < 300):
            raise KlaviyoError(f"create segment '{name}' HTTP {status}: {json.dumps(payload)[:400]}")
        return payload

    def ensure_defaults(self) -> dict:
        """Create any missing default segments; skip those that already exist."""
        existing = self.existing_names()
        created, skipped = [], []
        for name, definition in default_segments():
            if name in existing:
                skipped.append(name)
                continue
            self.create(name, definition)
            created.append(name)
        return {"created": created, "skipped": skipped}


def main() -> None:  # pragma: no cover - live, needs a real key
    seg = KlaviyoSegments()
    print(f"Ensuring default Halia segments in Klaviyo (revision {seg.revision}) ...")
    result = seg.ensure_defaults()
    for name in result["created"]:
        print(f"  created  {name}")
    for name in result["skipped"]:
        print(f"  exists   {name}  (left as-is — edit it in Klaviyo)")
    print("\nDone. Open Klaviyo → Audience → Segments to view/edit them.")


if __name__ == "__main__":  # pragma: no cover
    main()
