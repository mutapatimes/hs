"""Outreach pipeline (kanban): pure helpers, Shopify writes, staff attribution, zero persistence."""
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import halia.api.board as boardmod
from halia.api import shopify_auth
from halia.api.app import app
from halia.api.board import append_activity, load_pipe
from halia.api.shopify_auth import current_staff_id, session_claims
from halia.api.shopify_auth import require_shop
from scoring.shopify_pipeline import STAGES, stage_tag

SHOP = "brand.myshopify.com"


# ── pure helpers ──
def test_load_pipe_normalises():
    assert load_pipe(None) == {"stage": None, "assignee": None, "activity": []}
    assert load_pipe("not json")["activity"] == []
    p = load_pipe(json.dumps({"stage": "Contacted", "activity": [{"a": 1}]}))
    assert p["stage"] == "Contacted" and p["assignee"] is None


def test_append_activity_attributes_and_caps():
    p = load_pipe(None)
    append_activity(p, "moved:Contacted", "gid://staff/1", "Sarah", note="hi")
    e = p["activity"][-1]
    assert e["action"] == "moved:Contacted" and e["actor_name"] == "Sarah" and e["note"] == "hi"
    assert "at" in e and p["updated_at"]
    for i in range(80):
        append_activity(p, "note", None, "X")
    assert len(p["activity"]) <= 50


def test_stage_tag():
    assert stage_tag("Contacted") == "Halia Stage: Contacted"


# ── staff attribution from the session token ──
def test_current_staff_id_reads_sub(monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", "secret")
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", "key")
    token = jwt.encode({"dest": f"https://{SHOP}", "aud": "key", "sub": "gid://staff/9",
                        "exp": int(time.time()) + 300}, "secret", algorithm="HS256")

    class Req:
        headers = {"authorization": f"Bearer {token}"}
        query_params = {}
    assert session_claims(token)["sub"] == "gid://staff/9"
    assert current_staff_id(Req()) == "gid://staff/9"

    class NoTok:
        headers = {}
        query_params = {}
    assert current_staff_id(NoTok()) is None


# ── endpoints (fake Shopify sink; no network) ──
class _FakeSink:
    def __init__(self):
        self.meta = {}
        self.tags = set()

    def get_metafield(self, cid, key, namespace="halia"):
        return self.meta.get((cid, key))

    def set_metafield(self, cid, key, value, mtype="json", namespace="halia"):
        self.meta[(cid, key)] = value

    def tag_customer(self, cid, tags):
        self.tags.update(tags)

    def untag_customer(self, cid, tags):
        for t in tags:
            self.tags.discard(t)

    def _transport(self):
        return None


@pytest.fixture()
def client(monkeypatch):
    sink = _FakeSink()
    monkeypatch.setattr(boardmod, "_sink", lambda shop: sink)
    monkeypatch.setattr(boardmod, "current_staff_id", lambda req: "gid://staff/1")
    app.dependency_overrides[require_shop] = lambda: SHOP
    yield TestClient(app), sink
    app.dependency_overrides.pop(require_shop, None)


def _pipe(sink, cid="gid://C/1"):
    return json.loads(sink.meta[(cid, "pipeline")])


def test_add_tags_and_logs(client):
    c, sink = client
    r = c.post("/v1/board/add", json={"cid": "gid://C/1", "actor": "Sarah"})
    assert r.status_code == 200
    p = _pipe(sink)
    assert p["stage"] == "To reach out" and p["activity"][-1]["action"] == "added"
    assert p["activity"][-1]["actor_name"] == "Sarah"
    assert stage_tag("To reach out") in sink.tags


def test_move_swaps_stage_tag(client):
    c, sink = client
    c.post("/v1/board/add", json={"cid": "gid://C/1"})
    r = c.post("/v1/board/move", json={"cid": "gid://C/1", "stage": "Contacted", "actor": "Bob"})
    assert r.status_code == 200 and r.json()["pipeline"]["stage"] == "Contacted"
    assert stage_tag("Contacted") in sink.tags
    assert stage_tag("To reach out") not in sink.tags          # old stage tag removed
    assert _pipe(sink)["activity"][-1]["action"] == "moved:Contacted"


def test_move_rejects_unknown_stage(client):
    c, _ = client
    assert c.post("/v1/board/move", json={"cid": "gid://C/1", "stage": "Nope"}).status_code == 422


def test_assign_and_note(client):
    c, sink = client
    c.post("/v1/board/add", json={"cid": "gid://C/1"})
    c.post("/v1/board/assign", json={"cid": "gid://C/1", "assignee_name": "Priya"})
    c.post("/v1/board/note", json={"cid": "gid://C/1", "note": "prefers navy"})
    p = _pipe(sink)
    assert p["assignee"]["name"] == "Priya"
    assert p["activity"][-1]["action"] == "note" and p["activity"][-1]["note"] == "prefers navy"


def test_remove_clears_all_stage_tags(client):
    c, sink = client
    c.post("/v1/board/add", json={"cid": "gid://C/1"})
    c.post("/v1/board/remove", json={"cid": "gid://C/1"})
    assert not any(stage_tag(s) in sink.tags for s in STAGES)
    assert _pipe(sink)["stage"] is None


def test_get_board_lists_cards(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("scoring.shopify_pipeline.fetch_pipeline_cards",
                        lambda transport, retries=5: {"gid://C/1": {"cid": "gid://C/1",
                        "stage": "Contacted", "name": "Jane", "email": "j@x.com",
                        "assignee": None, "activity": []}})
    d = c.get("/v1/board").json()
    assert d["available"] and d["stages"] == STAGES and d["cards"][0]["name"] == "Jane"


def test_get_board_unavailable_for_non_shopify(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(boardmod, "_sink", lambda shop: (_ for _ in ()).throw(HTTPException(400, "x")))
    app.dependency_overrides[require_shop] = lambda: "woo.example.com"
    try:
        d = TestClient(app).get("/v1/board").json()
        assert d["available"] is False and d["cards"] == []
    finally:
        app.dependency_overrides.pop(require_shop, None)


# ── zero-retention guard: the board persists NOTHING in Halia ──
def test_no_new_halia_table():
    from halia.store import _TABLES
    joined = " ".join(_TABLES).lower()
    assert "pipeline" not in joined and "board" not in joined
