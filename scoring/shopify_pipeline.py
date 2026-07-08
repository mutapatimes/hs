"""Read the outreach-pipeline board from Shopify.

The board state lives entirely in the merchant's own store: a customer TAG ``Halia Stage: <Stage>``
(native, segmentable) plus a ``halia.pipeline`` customer METAFIELD holding the assignee + activity
log. Halia persists nothing. This module reads the carded customers (one ``customers(query:"tag:…")``
pull per stage) and returns their pipeline state for the board view.
"""
from __future__ import annotations

import json

STAGES = ["To reach out", "Contacted", "In conversation", "Actioned", "Parked"]
STAGE_TAG_PREFIX = "Halia Stage: "


def stage_tag(stage: str) -> str:
    return STAGE_TAG_PREFIX + stage


_CARDS_QUERY = """
query HaliaPipeline($q: String!, $cursor: String) {
  customers(first: 100, after: $cursor, query: $q) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      displayName
      email
      metafield(namespace: "halia", key: "pipeline") { value }
    }
  }
}
"""


def _parse_pipe(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        p = json.loads(raw)
        return p if isinstance(p, dict) else {}
    except (ValueError, TypeError):
        return {}


def fetch_pipeline_cards(transport, retries: int = 5) -> dict:
    """Return {cid(gid): {cid, stage, name, email, assignee, activity}} for every carded customer."""
    from scoring.shopify_fetch import _run
    cards: dict = {}
    for stage in STAGES:
        cursor = None
        while True:
            data = _run(transport, _CARDS_QUERY,
                        {"q": f'tag:"{stage_tag(stage)}"', "cursor": cursor}, retries)
            conn = data["customers"]
            for n in conn["nodes"]:
                cid = str(n.get("id"))
                pipe = _parse_pipe((n.get("metafield") or {}).get("value"))
                cards[cid] = {
                    "cid": cid,
                    "stage": pipe.get("stage") or stage,   # tag is the source of truth for the column
                    "name": n.get("displayName") or "",
                    "email": n.get("email") or "",
                    "assignee": pipe.get("assignee"),
                    "activity": pipe.get("activity") or [],
                }
            info = conn["pageInfo"]
            if not info["hasNextPage"]:
                break
            cursor = info["endCursor"]
    return cards
