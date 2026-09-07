"""The batched pipeline read behind the burst's "contacted recently" check.

One metafield read per client would cost a hand-picked burst 2N Admin API calls; nodes(ids:) reads
the pipeline metafield for up to 100 customers a call, in input order, without depending on the
customer search index. board.pipelines_for is the platform-neutral door onto it.
"""
from __future__ import annotations

import json

from halia.api import board
from scoring import shopify_pipeline as sp


class FakeTransport:
    def __init__(self, pipes: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.pipes = pipes or {}

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        nodes = []
        for gid in variables["ids"]:
            n = gid.rsplit("/", 1)[-1]
            if n == "404":
                nodes.append(None)                       # a deleted customer comes back null
                continue
            raw = self.pipes.get(n)
            nodes.append({"id": gid, "metafield": ({"value": raw} if raw is not None else None)})
        return {"data": {"nodes": nodes}}


def test_query_shape_and_chunking():
    t = FakeTransport()
    sp.fetch_pipeline_for(t, [str(i) for i in range(150)])
    assert len(t.calls) == 2                             # 150 ids -> 100 + 50
    q, v = t.calls[0]
    assert "nodes(ids: $ids)" in q and 'metafield(namespace: "halia", key: "pipeline")' in q
    assert v["ids"][0] == "gid://shopify/Customer/0" and len(v["ids"]) == 100
    assert len(t.calls[1][1]["ids"]) == 50


def test_gid_and_numeric_inputs_both_resolve_and_dedupe():
    pipe = json.dumps({"stage": "Contacted", "activity": [{"action": "contacted", "at": "2026-09-01T10:00:00+00:00"}]})
    t = FakeTransport({"123": pipe})
    out = sp.fetch_pipeline_for(t, ["gid://shopify/Customer/123", "123", " 123 ", "abc", ""])
    assert len(t.calls) == 1 and t.calls[0][1]["ids"] == ["gid://shopify/Customer/123"]
    assert out == {"123": json.loads(pipe)}              # keyed numeric, whichever form came in


def test_missing_null_and_unparseable_metafields_are_simply_absent():
    t = FakeTransport({"1": "not json", "2": json.dumps({"activity": []})})
    out = sp.fetch_pipeline_for(t, ["1", "2", "3", "404"])
    assert "1" not in out and "3" not in out and "404" not in out
    assert out["2"] == {"activity": []}


def test_no_ids_means_no_calls():
    t = FakeTransport()
    assert sp.fetch_pipeline_for(t, []) == {} and t.calls == []


# ── board.pipelines_for: the platform door ────────────────────────────────────────
class _ShopifySink:
    def __init__(self, transport): self._t = transport
    def _transport(self): return self._t


class _WooSink:
    def pipeline_cards(self):
        return {"7": {"cid": "7", "activity": [{"action": "note", "at": "x"}], "appointments": []},
                "8": {"cid": "8", "activity": [], "appointments": []}}


class _NoBoardSink:
    pass


def test_pipelines_for_routes_by_platform():
    t = FakeTransport({"7": json.dumps({"activity": [{"action": "contacted", "at": "y"}]})})
    assert board.pipelines_for(_ShopifySink(t), ["gid://shopify/Customer/7"])["7"]["activity"][0]["action"] == "contacted"
    woo = board.pipelines_for(_WooSink(), ["7", "9"])
    assert set(woo) == {"7"} and woo["7"]["activity"][0]["action"] == "note"
    assert board.pipelines_for(_NoBoardSink(), ["1"]) == {}
