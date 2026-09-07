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


# Exact fetch of the pipeline metafield for a chosen set of customers, for the burst's
# "contacted recently" check. nodes(ids:) rather than a customers(query:"id:… OR …") search: it
# does not depend on the search index (which lags a fresh capture), takes up to 250 ids a call,
# and answers in input order.
_BY_IDS_QUERY = """
query HaliaPipelineByIds($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Customer {
      id
      metafield(namespace: "halia", key: "pipeline") { value }
    }
  }
}
"""
_BY_IDS_CHUNK = 100


def _numeric_id(cid) -> str:
    """'gid://shopify/Customer/123' or '123' -> '123'. Payload rows carry the gid, the toolbar and
    the apps pass whichever they were handed."""
    return str(cid or "").strip().rsplit("/", 1)[-1]


def fetch_pipeline_for(transport, cids, retries: int = 5) -> dict:
    """{numeric_id: pipe} for the given customers, in ceil(N/100) calls instead of one metafield
    read each. Customers with no pipeline metafield are simply absent; a deleted id comes back
    null from Shopify and is skipped."""
    from scoring.shopify_fetch import _run
    ids = []
    seen: set[str] = set()
    for cid in cids or []:
        n = _numeric_id(cid)
        if n.isdigit() and n not in seen:
            seen.add(n)
            ids.append(n)
    out: dict = {}
    for i in range(0, len(ids), _BY_IDS_CHUNK):
        chunk = [f"gid://shopify/Customer/{n}" for n in ids[i:i + _BY_IDS_CHUNK]]
        data = _run(transport, _BY_IDS_QUERY, {"ids": chunk}, retries)
        for node in (data or {}).get("nodes") or []:
            if not node or not node.get("id"):
                continue
            pipe = _parse_pipe((node.get("metafield") or {}).get("value"))
            if pipe:
                out[_numeric_id(node["id"])] = pipe
    return out


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
                    "appointments": pipe.get("appointments") or [],
                }
            info = conn["pageInfo"]
            if not info["hasNextPage"]:
                break
            cursor = info["endCursor"]
    return cards
