"""Associate-feedback loop: aggregate tally (zero-retention) + neutral endpoint behaviour."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from halia.api import shopify_auth
from halia.api.app import app
from halia.cache import cache
from halia.schema import ScoreResult
from halia.store import ShopStore

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _vic(cid="c1", signals=("Premium email", "HNWI postcode")):
    return ScoreResult(matched=True, flagged=True, tier="A1", grade="A*", score=97,
                       is_priority=True, signal_count=len(signals), signals=list(signals),
                       reasons="; ".join(signals), gesture="", spend=680.0, hidden_vic=True,
                       customer_id=cid, email="vic@x.com", phone=None, confidence=2)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    store = ShopStore(db_path=tmp_path / "f.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    cache.clear()
    cache.set(SHOP, results=[_vic()], payload={}, orders=[])
    yield TestClient(app), store
    cache.clear()


def test_feedback_records_aggregate_tally_no_customer_data(client):
    c, store = client
    r = c.post("/v1/feedback", headers=_auth(), json={"customer_id": "c1", "verdict": "fit"})
    d = r.json()
    assert d["ok"] and d["verdict"] == "fit" and d["tagged"] is False   # no token -> no tag
    stats = {s["signal"]: s for s in store.get_feedback_stats(SHOP)}
    assert stats["Premium email"]["fit"] == 1 and stats["HNWI postcode"]["fit"] == 1
    # the tally holds signals only — never the customer id
    assert "c1" not in str(stats)


def test_fit_and_nofit_accumulate_into_precision(client):
    c, store = client
    c.post("/v1/feedback", headers=_auth(), json={"customer_id": "c1", "verdict": "fit"})
    c.post("/v1/feedback", headers=_auth(), json={"customer_id": "c1", "verdict": "nofit"})
    stats = c.get("/v1/feedback/stats", headers=_auth()).json()["stats"]
    pe = next(s for s in stats if s["signal"] == "Premium email")
    assert pe["fit"] == 1 and pe["nofit"] == 1 and pe["precision"] == 0.5


def test_bad_verdict_422(client):
    c, _ = client
    assert c.post("/v1/feedback", headers=_auth(), json={"customer_id": "c1", "verdict": "meh"}).status_code == 422


def test_unknown_customer_404(client):
    c, _ = client
    assert c.post("/v1/feedback", headers=_auth(), json={"customer_id": "nope", "verdict": "fit"}).status_code == 404


# ── outcome-based calibration endpoints ─────────────────────────────────────────
def test_feedback_calibration_apply_from_seeded_stats(client, monkeypatch):
    c, store = client
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    # Seed mixed verdicts directly: "Premium email" mostly good, "HNWI postcode" mostly bad.
    for _ in range(9):
        store.record_feedback(SHOP, ["Premium email"], "fit")
    store.record_feedback(SHOP, ["Premium email"], "nofit")
    for _ in range(9):
        store.record_feedback(SHOP, ["HNWI postcode"], "nofit")
    store.record_feedback(SHOP, ["HNWI postcode"], "fit")

    prev = c.get("/v1/calibrate/feedback", headers=_auth()).json()
    assert prev["verdicts"] == 20 and prev["report"]
    r = c.post("/v1/calibrate/feedback", headers=_auth()).json()
    assert r["ok"]
    # Good-call signal up, poor-call signal down, in the saved per-shop weights.
    from scoring.combine import SIGNAL_WEIGHTS
    assert r["saved"]["premium_email"] >= SIGNAL_WEIGHTS["premium_email"]
    assert r["saved"]["hnwi_postcode"] < SIGNAL_WEIGHTS["hnwi_postcode"]


def test_feedback_calibration_400_without_feedback(client):
    c, _ = client
    assert c.post("/v1/calibrate/feedback", headers=_auth()).status_code == 400
