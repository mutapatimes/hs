"""Halia -> Brevo list sync that drives the lifecycle email journeys.

No network: the tiny `_call` seam is monkeypatched. Proves demo requests land on the Demo list
and clients land on the Clients list (unlinking Demo), and that the /subscribe endpoint only
starts the Brevo journey for demo requests, not plain newsletter signups.
"""
import pytest
from fastapi.testclient import TestClient

import halia.notify_brevo as nb
from halia.api import shopify_auth
from halia.api.app import app
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "j.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    return TestClient(app), store


def test_noop_without_api_key(monkeypatch):
    monkeypatch.delenv("HALIA_BREVO_API_KEY", raising=False)
    assert nb.configured() is False
    assert nb.add_demo_lead("a@b.com") is False        # silent no-op, never raises


def test_demo_and_client_build_correct_body(monkeypatch):
    monkeypatch.setenv("HALIA_BREVO_API_KEY", "xkeysib-test")
    monkeypatch.setattr("halia.config.BREVO_LIST_DEMO", "3")
    monkeypatch.setattr("halia.config.BREVO_LIST_CLIENTS", "4")
    calls = []
    monkeypatch.setattr(nb, "_call", lambda body: calls.append(body) or 201)

    assert nb.add_demo_lead("Lead@Ex.com") is True
    demo = calls[-1]
    assert demo["email"] == "lead@ex.com" and demo["listIds"] == [3] and demo["updateEnabled"]
    assert "unlinkListIds" not in demo

    assert nb.add_client("ceo@store.com", attributes={"FIRSTNAME": "Aubin"}) is True
    cli = calls[-1]
    assert cli["listIds"] == [4] and cli["unlinkListIds"] == [3]
    assert cli["attributes"] == {"FIRSTNAME": "Aubin"}


def test_subscribe_demo_source_starts_journey(client, monkeypatch):
    c, store = client
    seen = []
    monkeypatch.setattr(nb, "add_demo_lead", lambda email, attributes=None: seen.append(email) or True)
    r = c.post("/subscribe", json={"email": "demo@lead.com", "source": "demo"})
    assert r.status_code == 200 and seen == ["demo@lead.com"]
    assert store.count_subscribers() >= 1                # still recorded as a subscriber


def test_subscribe_newsletter_does_not_start_journey(client, monkeypatch):
    c, _ = client
    called = []
    monkeypatch.setattr(nb, "add_demo_lead", lambda *a, **k: called.append(1) or True)
    r = c.post("/subscribe", json={"email": "news@lead.com"})       # no source -> newsletter only
    assert r.status_code == 200 and called == []
