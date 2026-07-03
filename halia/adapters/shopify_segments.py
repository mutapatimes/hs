"""ShopifySegments — create a native Shopify customer segment via the Admin GraphQL API.

Halia already tags scored customers `Halia:{grade}`. This turns a dashboard selection into a Shopify
**customer segment** (a query over a Halia tag) so the merchant can pick it as the audience in
Shopify Email and send natively — Halia prepares the audience, the merchant sends (Shopify has no API
for an app to send the campaign itself). Reuses the same injectable transport + throttle-aware `_run`
as the read/write layers, so it is unit-testable against a fake Shopify. Needs only customer read
access, which Halia already holds (read_customers / write_customers).
"""
from __future__ import annotations

_SEGMENT_CREATE = """
mutation HaliaSegmentCreate($name: String!, $query: String!) {
  segmentCreate(name: $name, query: $query) {
    segment { id name }
    userErrors { field message }
  }
}
"""


def segment_numeric_id(gid: str) -> str:
    """gid://shopify/Segment/123 -> '123' (for the admin deep link)."""
    return str(gid or "").rsplit("/", 1)[-1]


def create_segment(transport, name: str, query: str, retries: int = 5) -> dict:
    """Create a customer segment; returns {"id", "name"}. Raises ShopifyError on API errors."""
    from scoring.shopify_fetch import ShopifyError, _run
    data = _run(transport, _SEGMENT_CREATE, {"name": name, "query": query}, retries)
    result = data.get("segmentCreate") or {}
    errors = result.get("userErrors") or []
    if errors:
        raise ShopifyError(f"segmentCreate: {errors}")
    seg = result.get("segment") or {}
    return {"id": seg.get("id"), "name": seg.get("name") or name}
