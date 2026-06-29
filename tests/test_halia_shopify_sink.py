"""ShopifySink builds correct write-back mutations (against a fake transport)."""
import json

import pytest

from halia.adapters.shopify_sink import NAMESPACE, ShopifySink
from halia.schema import ScoreResult


def _result(cid, grade="A*", score=99):
    return ScoreResult(
        matched=True, flagged=True, tier="A1", grade=grade, score=score,
        is_priority=True, signal_count=2, signals=["Work email"],
        reasons="Work email: GS; HNWI postcode: SW1X", gesture="coffee", spend=400.0,
        hidden_vic=True, customer_id=cid, email=f"{cid}@x.com", phone=None,
    )


class FakeShopify:
    """Records every mutation and returns a clean (no userErrors) response."""

    def __init__(self):
        self.calls = []

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        field = "metafieldsSet" if "metafieldsSet" in query else "tagsAdd"
        return {"data": {field: {"userErrors": []}}}


def test_push_writes_metafields_and_tag():
    fake = FakeShopify()
    ShopifySink(transport=fake).push_many([_result("123")])

    metas = [v for q, v in fake.calls if "metafieldsSet" in q]
    tags = [v for q, v in fake.calls if "tagsAdd" in q]
    assert len(metas) == 1 and len(tags) == 1

    fields = {m["key"]: m for m in metas[0]["metafields"]}
    assert set(fields) == {"grade", "score", "reasons", "scored_at"}
    assert all(m["ownerId"] == "gid://shopify/Customer/123" for m in metas[0]["metafields"])
    assert all(m["namespace"] == NAMESPACE for m in metas[0]["metafields"])
    assert fields["grade"]["value"] == "A*" and fields["score"]["value"] == "99"
    assert tags[0] == {"id": "gid://shopify/Customer/123", "tags": ["Halia:A*"]}


def test_existing_gid_is_passed_through():
    fake = FakeShopify()
    ShopifySink(transport=fake).push_many([_result("gid://shopify/Customer/999")])
    metas = [v for q, v in fake.calls if "metafieldsSet" in q][0]
    assert metas["metafields"][0]["ownerId"] == "gid://shopify/Customer/999"


def test_metafields_batched_in_chunks_of_25():
    fake = FakeShopify()
    # 7 customers x 4 metafields = 28 inputs -> 2 metafieldsSet calls (25 + 3).
    ShopifySink(transport=fake).push_many([_result(str(i)) for i in range(7)])
    meta_calls = [v for q, v in fake.calls if "metafieldsSet" in q]
    assert [len(c["metafields"]) for c in meta_calls] == [25, 3]


def test_user_errors_raise():
    def broken(query, variables):
        return {"data": {"metafieldsSet": {"userErrors": [{"field": "x", "message": "nope"}]}}}

    from scoring.shopify_fetch import ShopifyError
    with pytest.raises(ShopifyError):
        ShopifySink(transport=broken).push_many([_result("1")])
