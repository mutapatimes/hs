"""Closing the calibration loop: per-merchant weights persist and reach live scoring."""
import time

import jwt
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from halia.api import settings as settings_mod
from halia.api.app import app
from halia.api.settings import _clean_signal_weights, set_signal_weights, settings_for
from halia.store import ShopStore
from scoring.combine import score_customers

SECRET, KEY, SHOP = "test-app-secret", "test-api-key", "acme.myshopify.com"


def _auth():
    tok = jwt.encode({"iss": f"https://{SHOP}/admin", "dest": f"https://{SHOP}", "aud": KEY,
                      "sub": "1", "exp": int(time.time()) + 3600}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _scored():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(200):
        prime = i % 2 == 0
        rows.append({"Name": f"C{i}", "Email": f"u{i}@gmail.com",
                     "LATEST_BILLING_ZIP": "SW10 9SJ" if prime else "M1 1AA",
                     "Spent": max(0.0, float(rng.normal(4000 if prime else 500, 150)))})
    return score_customers(pd.DataFrame(rows))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("halia.config.SHOPIFY_API_KEY", KEY)
    monkeypatch.setattr("halia.config.SHOPIFY_API_SECRET", SECRET)
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    # No real store to pull from — feed calibration a synthetic scored frame.
    monkeypatch.setattr("halia.api.data.scored_frame_for", lambda shop: _scored())
    yield TestClient(app), store


# ── validator ────────────────────────────────────────────────────────────────
def test_clean_signal_weights_filters_and_bounds():
    out = _clean_signal_weights({"hnwi_postcode": "4", "bogus_key": 3, "work_email": 99, "x": None})
    assert out == {"hnwi_postcode": 4, "work_email": 10}  # unknown dropped, bounded to 10


def test_clean_signal_weights_empty_is_none():
    assert _clean_signal_weights({}) is None
    assert _clean_signal_weights("nope") is None


# ── persistence round-trip ─────────────────────────────────────────────────────
def test_settings_default_signal_weights_is_none(client):
    c, _ = client
    assert c.get("/v1/settings", headers=_auth()).json()["signal_weights"] is None


def test_set_and_settings_for_roundtrip(client, monkeypatch):
    _, store = client
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    set_signal_weights(SHOP, {"hnwi_postcode": 5})
    assert settings_for(SHOP)["signal_weights"] == {"hnwi_postcode": 5}


def test_save_settings_preserves_calibrated_weights(client, monkeypatch):
    c, store = client
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    set_signal_weights(SHOP, {"hnwi_postcode": 5})
    # A normal settings save (UI never sends signal_weights) must NOT wipe them.
    c.post("/v1/settings", headers=_auth(), json={"vic_threshold": 7000})
    assert settings_for(SHOP)["signal_weights"] == {"hnwi_postcode": 5}
    assert settings_for(SHOP)["vic_threshold"] == 7000


# ── endpoints ──────────────────────────────────────────────────────────────────
def test_calibrate_preview_returns_report_without_saving(client):
    c, _ = client
    r = c.get("/v1/calibrate", headers=_auth()).json()
    assert r["current"] is None  # not saved
    assert r["suggested"]["hnwi_postcode"] >= 3  # predictive -> up-weighted
    assert any(row["key"] == "hnwi_postcode" for row in r["report"])


def test_calibrate_apply_saves_and_reaches_settings(client, monkeypatch):
    c, store = client
    r = c.post("/v1/calibrate", headers=_auth()).json()
    assert r["ok"] and r["saved"]["hnwi_postcode"] >= 3
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    assert settings_for(SHOP)["signal_weights"] == r["saved"]


def test_calibrate_reset_clears(client, monkeypatch):
    c, store = client
    c.post("/v1/calibrate", headers=_auth())
    assert c.delete("/v1/calibrate", headers=_auth()).json() == {"ok": True, "saved": None}
    monkeypatch.setattr("halia.api.settings.shop_store", lambda: store)
    assert settings_for(SHOP)["signal_weights"] is None


def test_calibrate_400_when_no_store(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.api.data.scored_frame_for", lambda shop: None)
    assert c.get("/v1/calibrate", headers=_auth()).status_code == 400
    assert c.post("/v1/calibrate", headers=_auth()).status_code == 400
