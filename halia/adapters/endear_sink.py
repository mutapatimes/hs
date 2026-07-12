"""EndearSink — push Halia's hidden-VIC intelligence onto Endear customers (LIVE).

Endear (endearhq.com) is a retail clienteling CRM. Each scored customer is upserted into the
merchant's Endear brand by EXTERNAL ID — the same Shopify / WooCommerce customer id Endear already
syncs from its own store connection — and enriched with:

  - tags     : "Halia VIC", "Halia: A"  (so associates can filter / segment / assign off them)
  - custom fields : halia_grade, halia_score, halia_vic, halia_signals

…all in one ``bulkUpsertExternalCustomers`` call. A store team then sees the Halia grade on the
customer they already know and can clientele the right people. Halia is the discovery layer;
Endear is where the outreach happens.

Auth is a per-brand **Endear API key** (header ``X-Endear-Api-Key``); calls are GraphQL over POST
to ``https://api.endearhq.com/graphql``. The HTTP call is injectable as ``transport`` so this is
unit-testable against a fake Endear with no network.

Nothing is stored by Halia: the customers pushed come from the in-memory scored list, and this
routes that intelligence into the merchant's OWN Endear account.

Docs: https://developers.endearhq.com  (GraphQL Admin API). Verified against the live schema:
bulkUpsertExternalCustomers(customers:[ExternalCustomerInput!]!), ExternalCustomerInput{id,tags,
email_address,phone_number,custom_fields:[{key,values}]}, createCustomerField(key,label,type…),
currentBrand. Rate limit: 120 requests/min.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from halia.schema import ScoreResult

_ENDPOINT = "https://api.endearhq.com/graphql"

# Halia custom fields defined on the Endear brand (key, label, CustomerFieldType enum).
FIELDS = [
    ("halia_grade", "Halia Grade", "STRING"),
    ("halia_score", "Halia Score", "NUMBER"),
    ("halia_vic", "Halia Hidden VIC", "STRING"),
    ("halia_signals", "Halia Signals", "STRING"),
]

_VALIDATE = "query{currentBrand{__typename}}"
_ENSURE_FIELD = (
    "mutation($key:String!,$label:String!,$type:CustomerFieldType!){"
    "createCustomerField(key:$key,label:$label,type:$type,allowMultiple:false,"
    "isUserEditable:true){__typename}}"
)
_UPSERT = (
    "mutation($customers:[ExternalCustomerInput!]!){"
    "bulkUpsertExternalCustomers(customers:$customers){__typename}}"
)


class EndearError(RuntimeError):
    """A GraphQL or transport error from the Endear Admin API."""


def _http_transport(api_key: str):
    """Real transport: (query, variables) -> (status, json). Per-brand key in the api-key header."""
    import requests

    def _call(query: str, variables: dict | None = None) -> tuple[int, dict]:
        resp = requests.post(
            _ENDPOINT,
            headers={"Content-Type": "application/json", "X-Endear-Api-Key": api_key},
            json={"query": query, "variables": variables or {}}, timeout=30)
        try:
            payload = resp.json()
        except ValueError:
            payload = {"raw": resp.text}
        return resp.status_code, payload

    return _call


def _first_error(payload: object) -> str | None:
    """GraphQL returns 200 with an `errors` array; surface the first message (e.g. UNAUTHENTICATED)."""
    if isinstance(payload, dict):
        errs = payload.get("errors")
        if errs:
            return str((errs[0] or {}).get("message") or errs[0])
    return None


def _external_id(result: ScoreResult) -> str:
    """External id used to match Endear's existing customer. Shopify gids collapse to their trailing
    numeric id (how Shopify external ids usually appear in Endear); other ids pass through."""
    cid = str(result.customer_id or "")
    if "gid://" in cid or "/Customer/" in cid:
        digits = re.findall(r"\d+", cid)
        return digits[-1] if digits else cid
    return cid


def _tags(result: ScoreResult) -> list[str]:
    tags = []
    if result.hidden_vic:
        tags.append("Halia VIC")
    if result.grade and result.grade != "—":
        tags.append(f"Halia: {result.grade}")
    return tags


def _custom_fields(result: ScoreResult) -> list[dict]:
    return [
        {"key": "halia_grade", "values": [result.grade or ""]},
        {"key": "halia_score", "values": [str(result.score) if result.score is not None else ""]},
        {"key": "halia_vic", "values": ["Yes" if result.hidden_vic else "No"]},
        {"key": "halia_signals", "values": [", ".join(result.signals or [])]},
    ]


def _customer_input(result: ScoreResult) -> dict:
    ci: dict = {"id": _external_id(result), "tags": _tags(result),
                "custom_fields": _custom_fields(result)}
    if result.email:
        ci["email_address"] = result.email
    if result.phone:
        ci["phone_number"] = result.phone
    return ci


class EndearSink:
    name = "endear"

    def __init__(self, api_key: str, transport=None):
        self.api_key = api_key
        self._transport = transport

    def _send(self, query: str, variables: dict | None = None) -> tuple[int, dict]:
        if self._transport is None:
            self._transport = _http_transport(self.api_key)
        return self._transport(query, variables)

    def validate_key(self) -> dict:
        """A cheap authed query to confirm the key. currentBrand errors UNAUTHENTICATED on a bad key."""
        status, payload = self._send(_VALIDATE)
        err = _first_error(payload)
        if err or not (200 <= status < 300):
            raise EndearError(err or f"HTTP {status}")
        return {"ok": True}

    def ensure_fields(self) -> None:
        """Define the Halia custom fields on the brand. Idempotent: an 'already exists' error for a
        key that's already defined is ignored; any other error is surfaced."""
        for key, label, typ in FIELDS:
            _, payload = self._send(_ENSURE_FIELD, {"key": key, "label": label, "type": typ})
            err = _first_error(payload)
            if err and not any(w in err.lower() for w in ("exist", "already", "duplicate", "taken")):
                raise EndearError(err)

    def upsert(self, results: Iterable[ScoreResult]) -> int:
        """Bulk-upsert customers by external id, tagging + setting Halia fields. Returns the count."""
        targets = [r for r in results if r and (r.customer_id or r.email)]
        pushed = 0
        for i in range(0, len(targets), 100):        # modest batches (respect the 120 req/min limit)
            chunk = targets[i:i + 100]
            status, payload = self._send(_UPSERT, {"customers": [_customer_input(r) for r in chunk]})
            err = _first_error(payload)
            if err or not (200 <= status < 300):
                raise EndearError(err or f"HTTP {status}")
            pushed += len(chunk)
        return pushed

    def push_many(self, results: Iterable[ScoreResult]) -> int:
        return self.upsert(list(results))
