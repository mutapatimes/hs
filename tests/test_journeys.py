"""The lifecycle-email engine: enrollment, the scheduler, weekly recurrence, and unsubscribe.

No network — a fake `send` captures (to, subject). A temp ShopStore is injected, and time is
driven explicitly so the +4/+3/+7 day gaps are exercised deterministically.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from halia import emails, journeys
from halia.api import shopify_auth
from halia.api.app import app
from halia.store import ShopStore


@pytest.fixture()
def st(tmp_path):
    return ShopStore(db_path=tmp_path / "j.db")


def _recorder():
    sent = []
    def send(to, subject, html, text=None, shop=None):
        sent.append((to, subject, html))
        return True
    return sent, send


def _base_now():
    return datetime.now(timezone.utc) + timedelta(seconds=1)


def test_demo_drip_runs_on_the_4day_cadence(st):
    sent, send = _recorder()
    assert journeys.enroll("lead@ex.com", "demo", store=st) is True
    n0 = _base_now()
    journeys.run_due(now=n0, send=send, store=st)                     # intro (immediate)
    assert len(sent) == 1 and "demo" in sent[-1][1].lower()
    journeys.run_due(now=n0 + timedelta(days=1), send=send, store=st)  # too early
    assert len(sent) == 1
    for day in (4, 8, 12):
        journeys.run_due(now=n0 + timedelta(days=day), send=send, store=st)
    assert len(sent) == 4                                             # 4-email sequence complete
    journeys.run_due(now=n0 + timedelta(days=20), send=send, store=st)
    assert len(sent) == 4                                             # finished, no repeats


def test_client_series(st):
    sent, send = _recorder()
    journeys.enroll("ceo@store.com", "client", {"first": "Aubin"}, store=st)
    n0 = _base_now()
    journeys.run_due(now=n0, send=send, store=st)
    journeys.run_due(now=n0 + timedelta(days=3), send=send, store=st)
    journeys.run_due(now=n0 + timedelta(days=7), send=send, store=st)
    assert [s[1] for s in sent] == ["Welcome to Halia",
                                    "Turn a hidden VIC into a moment",
                                    "Good call, bad call: the habit that sharpens Halia"]


def test_weekly_recurs_and_rotates(st):
    sent, send = _recorder()
    journeys.enroll("ceo@store.com", "weekly", {"shop": "s.myshopify.com"}, store=st)
    n0 = _base_now()
    journeys.run_due(now=n0, send=send, store=st)                     # not due for 7 days
    assert sent == []
    journeys.run_due(now=n0 + timedelta(days=7), send=send, store=st)
    journeys.run_due(now=n0 + timedelta(days=14), send=send, store=st)
    journeys.run_due(now=n0 + timedelta(days=21), send=send, store=st)
    assert [s[1] for s in sent] == ["New potential VICs are waiting on Halia",
                                    "One tap that makes your grades sharper",
                                    "Refresh your outreach, keep what works"]


def test_unsubscribe_stops_all_sends(st):
    sent, send = _recorder()
    journeys.enroll("lead@ex.com", "demo", store=st)
    st.suppress_email("lead@ex.com")
    journeys.run_due(now=_base_now(), send=send, store=st)
    assert sent == []                                                # suppressed -> nothing due


def test_email_renders_with_unsub_and_domain():
    subject, html, text = emails.render("client_welcome", {"first": "Aubin"},
                                        journeys.unsub_url("ceo@store.com"))
    assert subject == "Welcome to Halia"
    assert "haliascore.com" in html and "/email/unsubscribe?" in html
    assert "Aubin" in html and "Welcome" in html


# ── routes ───────────────────────────────────────────────────────────────────────
@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "r.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    return TestClient(app), store


def test_unsubscribe_route(client):
    c, store = client
    email = "lead@ex.com"
    sig = journeys._sig(email)
    assert c.get(f"/email/unsubscribe?e={email}&s={sig}").status_code == 200
    assert store.is_suppressed(email) is True
    assert c.get(f"/email/unsubscribe?e={email}&s=bogus").status_code == 400


def test_cron_requires_key(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr("halia.config.CRON_KEY", None)
    assert c.post("/internal/cron/run").status_code == 403
    monkeypatch.setattr("halia.config.CRON_KEY", "cronk")
    assert c.post("/internal/cron/run", headers={"X-Cron-Key": "nope"}).status_code == 403
    r = c.post("/internal/cron/run", headers={"X-Cron-Key": "cronk"})
    assert r.status_code == 200 and "sent" in r.json()
