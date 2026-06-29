"""ShopifySink — write the Halia score BACK into Shopify (the first lit surface).

So the merchant sees the grade where they already work: each scored customer gets
- **customer metafields** under the `halia` namespace (`grade`, `score`, `reasons`,
  `scored_at`) — queryable, shown on the customer page, usable in Flow/segments; and
- a **tag** `Halia:{grade}` — the quickest way to segment in the Shopify admin.

Uses the Admin **GraphQL** `metafieldsSet` + `tagsAdd` mutations over the same
injectable `transport` + throttle-aware `_run` the read layer uses, so it is fully
unit-testable against a fake Shopify. Requires the `write_customers` scope.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from halia.ports import ScoreSink
from halia.schema import ScoreResult

NAMESPACE = "halia"
_METAFIELDS_CHUNK = 25  # Shopify caps metafieldsSet at 25 inputs per call.

_SET_METAFIELDS = """
mutation HaliaSetMetafields($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    userErrors { field message }
  }
}
"""

_ADD_TAGS = """
mutation HaliaAddTags($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    userErrors { field message }
  }
}
"""


def _gid(customer_id: str) -> str:
    """Accept a raw numeric id or an already-formed GID; return a customer GID."""
    cid = str(customer_id)
    return cid if cid.startswith("gid://") else f"gid://shopify/Customer/{cid}"


def _metafields_for(result: ScoreResult, owner: str, scored_at: str) -> list[dict]:
    fields = {
        "grade": ("single_line_text_field", result.grade),
        "score": ("number_integer", str(int(result.score or 0))),
        "reasons": ("multi_line_text_field", result.reasons or ""),
        "scored_at": ("single_line_text_field", scored_at),
    }
    return [
        {"ownerId": owner, "namespace": NAMESPACE, "key": key, "type": mtype, "value": value}
        for key, (mtype, value) in fields.items()
    ]


class ShopifySink(ScoreSink):
    name = "shopify"

    def __init__(self, transport=None, retries: int = 5):
        self.transport = transport
        self.retries = retries

    def _transport(self):
        if self.transport is None:
            from scoring.shopify_fetch import http_transport
            self.transport = http_transport()
        return self.transport

    def _run(self, query: str, variables: dict) -> dict:
        from scoring.shopify_fetch import _run
        return _run(self._transport(), query, variables, self.retries)

    def push_many(self, results: Iterable[ScoreResult]) -> None:
        scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        targets = [r for r in results if r.customer_id]

        # 1) Metafields — batched across customers (≤25 inputs per call).
        metafields: list[dict] = []
        for r in targets:
            metafields += _metafields_for(r, _gid(r.customer_id), scored_at)
        for i in range(0, len(metafields), _METAFIELDS_CHUNK):
            chunk = metafields[i:i + _METAFIELDS_CHUNK]
            data = self._run(_SET_METAFIELDS, {"metafields": chunk})
            _raise_user_errors(data, "metafieldsSet")

        # 2) Tags — one mutation per customer (tagsAdd targets a single node).
        for r in targets:
            data = self._run(_ADD_TAGS, {"id": _gid(r.customer_id), "tags": [f"Halia:{r.grade}"]})
            _raise_user_errors(data, "tagsAdd")


def _raise_user_errors(data: dict, field: str) -> None:
    errors = (data.get(field) or {}).get("userErrors") or []
    if errors:
        from scoring.shopify_fetch import ShopifyError
        raise ShopifyError(f"{field}: {errors}")
