"""The merchant and seat journeys beyond onboarding: the free scan, the merchant gone quiet,
cancellation and win-back, the season calendar, birthdays. No network; time is driven."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from halia import emails, journeys
from halia.api import billing, shopify_auth
from halia.api.tenant_auth import hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "maison.myshopify.com"


@pytest.fixture()
def st(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "j2.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(new_token()))
    store.save_settings(SHOP, json.dumps({"account_email": "owner@maison.com"}))
    cache.clear()
    cache.set(SHOP, results=[], payload={
        "stat_count": "212", "stat_latent": "£1.4m", "stat_scored": "40,000",
        "data": [{"cid": "1", "grade": "A*", "band": "lapsed", "known": True, "cart": {"value": 900}},
                 {"cid": "2", "grade": "A", "band": "active", "known": False},
                 {"cid": "3", "grade": "B", "band": "lapsed", "known": True}]}, orders=[])
    yield store
    cache.clear()


def _recorder():
    sent = []
    def send(to, subject, html, text=None, shop=None):
        sent.append((to, subject, html))
        return True
    return sent, send


def _paid(monkeypatch, value):
    monkeypatch.setattr(billing, "is_paid", lambda shop: value)


# ── free scan ────────────────────────────────────────────────────────────────
def test_free_scan_series_carries_the_numbers_and_stops_on_subscription(st, monkeypatch):
    _paid(monkeypatch, False)
    sent, send = _recorder()
    assert journeys.enroll_freescan(SHOP, store=st)
    n0 = datetime.now(timezone.utc) + timedelta(seconds=1)
    journeys.run_due(now=n0, send=send, store=st)
    assert sent[0][0] == "owner@maison.com" and sent[0][1] == "Your book, scored"
    assert "212" in sent[0][2] and "£1.4m" in sent[0][2]
    journeys.run_due(now=n0 + timedelta(days=3), send=send, store=st)
    assert sent[1][1] == "Who is behind the grades" and "<b>1</b> of your hidden VICs grade A" in sent[1][2]
    _paid(monkeypatch, True)                                   # they chose a plan
    journeys.run_due(now=n0 + timedelta(days=10), send=send, store=st)
    assert len(sent) == 2
    assert st.due_journeys("2099-01-01T00:00:00+00:00") == []


def test_free_scan_needs_an_owner_email_and_an_unpaid_store(st, monkeypatch):
    _paid(monkeypatch, True)
    assert journeys.enroll_freescan(SHOP, store=st) is False
    _paid(monkeypatch, False)
    st.save_settings(SHOP, json.dumps({}))
    assert journeys.enroll_freescan(SHOP, store=st) is False


def test_subscribing_swaps_free_scan_for_the_client_series(st, monkeypatch):
    _paid(monkeypatch, False)
    journeys.enroll_freescan(SHOP, store=st)
    journeys.on_subscribed(SHOP, store=st)
    assert not st.journey_exists("owner@maison.com", "freescan")
    assert st.journey_exists("owner@maison.com", "client") and st.journey_exists("owner@maison.com", "weekly")


# ── the merchant gone quiet ───────────────────────────────────────────────────
def test_quiet_merchant_is_nudged_every_fortnight_until_they_open_halia(st, monkeypatch):
    _paid(monkeypatch, True)
    sent, send = _recorder()
    st.touch_tenant(SHOP)
    now = datetime.now(timezone.utc)
    assert journeys.ensure_journeys(store=st)["dormant"] == 0          # opened just now
    monkeypatch.setattr(journeys, "_now", lambda: now + timedelta(days=15))
    assert journeys.ensure_journeys(store=st)["dormant"] == 1
    journeys.run_due(now=now + timedelta(days=15), send=send, store=st)
    assert len(sent) == 1 and sent[0][1] == "Your book has moved"
    assert "<b>212</b> hidden VICs" in sent[0][2] and "<b>2</b> proven clients gone quiet" in sent[0][2]
    assert "<b>1</b> open basket holding £900" in sent[0][2]
    journeys.run_due(now=now + timedelta(days=29), send=send, store=st)
    assert len(sent) == 2
    monkeypatch.setattr("halia.store._now", lambda: (now + timedelta(days=42)).isoformat())
    st.touch_tenant(SHOP)                                               # they came back
    journeys.run_due(now=now + timedelta(days=43), send=send, store=st)
    assert len(sent) == 2 and not st.journey_exists("owner@maison.com", "dormant")


# ── cancellation and win-back ─────────────────────────────────────────────────
def test_cancel_ending_fires_five_days_before_the_period_ends(st, monkeypatch):
    sent, send = _recorder()
    end = datetime.now(timezone.utc) + timedelta(days=20)
    assert journeys.enroll_cancel_ending(SHOP, end.timestamp(), store=st)
    monkeypatch.setattr(billing, "billing_state", lambda shop: {"cancel_at_period_end": True})
    journeys.run_due(now=end - timedelta(days=6), send=send, store=st)
    assert sent == []
    journeys.run_due(now=end - timedelta(days=4), send=send, store=st)
    assert len(sent) == 1 and sent[0][1].startswith("Your plan ends on " + end.date().isoformat())
    assert "Keep my plan" in sent[0][2] and "212" in sent[0][2]


def test_cancel_ending_is_dropped_when_they_resume(st, monkeypatch):
    sent, send = _recorder()
    end = datetime.now(timezone.utc) + timedelta(days=3)
    journeys.enroll_cancel_ending(SHOP, end.timestamp(), store=st)
    journeys.cancel_cancel_ending(SHOP, store=st)
    journeys.run_due(now=end, send=send, store=st)
    assert sent == []


def test_winback_at_30_and_90_days_stops_if_they_return(st, monkeypatch):
    _paid(monkeypatch, False)
    sent, send = _recorder()
    assert journeys.enroll_winback(SHOP, store=st)
    n0 = datetime.now(timezone.utc)
    journeys.run_due(now=n0 + timedelta(days=29), send=send, store=st)
    assert sent == []
    journeys.run_due(now=n0 + timedelta(days=31), send=send, store=st)
    assert [s[1] for s in sent] == ["Your book, a month on"]
    _paid(monkeypatch, True)
    journeys.run_due(now=n0 + timedelta(days=95), send=send, store=st)
    assert len(sent) == 1


def test_billing_change_hooks_route_to_the_right_journey(st, monkeypatch):
    _paid(monkeypatch, False)
    billing.on_billing_change(SHOP, "canceled")
    assert st.journey_exists("owner@maison.com", "winback")
    billing.on_billing_change(SHOP, "active")
    assert not st.journey_exists("owner@maison.com", "winback") and st.journey_exists("owner@maison.com", "client")


# ── season moments and birthdays to seats ────────────────────────────────────
def test_season_moment_two_weeks_out_with_the_fit_count(st, monkeypatch):
    _paid(monkeypatch, True)
    sent, send = _recorder()
    sarah = st.create_seat(SHOP, "Sarah Bloom", hash_token(new_token()), "sarah@m.com")
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(journeys, "_now", lambda: now)
    assert journeys.enroll_season("sarah@m.com", sarah, SHOP, "Maison", "Sarah", store=st)
    journeys.run_due(now=datetime(2026, 10, 19, 7, tzinfo=timezone.utc), send=send, store=st)
    assert sent == []                                                   # preview starts 3 Nov: due 20 Oct
    journeys.run_due(now=datetime(2026, 10, 20, 7, tzinfo=timezone.utc), send=send, store=st)
    assert len(sent) == 1 and sent[0][1] == "Private preview of the festive collection, two weeks out"
    assert "2 clients in the book fit it" in sent[0][2]                # A* + A
    journeys.run_due(now=datetime(2026, 11, 3, 7, tzinfo=timezone.utc), send=send, store=st)
    assert len(sent) == 2 and sent[1][1].startswith("Gifting appointments")


def test_birthdays_weekly_only_when_there_are_some(st, monkeypatch):
    _paid(monkeypatch, True)
    sent, send = _recorder()
    sarah = st.create_seat(SHOP, "Sarah Bloom", hash_token(new_token()), "sarah@m.com")
    monkeypatch.setattr(journeys, "_now", lambda: datetime(2026, 9, 2, 12, tzinfo=timezone.utc))   # a Wednesday
    assert journeys.enroll_birthdays("sarah@m.com", sarah, SHOP, "Maison", "Sarah", store=st)
    monkeypatch.setattr(journeys, "_birthdays_payload", lambda shop: None)
    journeys.run_due(now=datetime(2026, 9, 7, 7, tzinfo=timezone.utc), send=send, store=st)     # Monday
    assert sent == []
    monkeypatch.setattr(journeys, "_birthdays_payload", lambda shop: {"count": 2, "rows": [
        {"name": "Grace Ladoja", "date": "2026-09-16", "in_days": 2, "grade": "A*"},
        {"name": "Tom Lee", "date": "2026-09-20", "in_days": 6, "grade": ""}]})
    journeys.run_due(now=datetime(2026, 9, 14, 7, tzinfo=timezone.utc), send=send, store=st)
    assert len(sent) == 1 and sent[0][1] == "2 birthdays in the next fortnight"
    assert "Grace Ladoja" in sent[0][2] and "in 2 days" in sent[0][2]
    st.revoke_seat(SHOP, sarah)
    journeys.run_due(now=datetime(2026, 9, 21, 7, tzinfo=timezone.utc), send=send, store=st)
    assert len(sent) == 1


def test_ensure_journeys_enrols_seats_on_all_three(st, monkeypatch):
    _paid(monkeypatch, True)
    st.create_seat(SHOP, "Sarah Bloom", hash_token(new_token()), "sarah@m.com")
    out = journeys.ensure_journeys(store=st)
    assert out["monthly"] == 1 and out["season"] == 1 and out["birthdays"] == 1
    assert journeys.ensure_journeys(store=st) == {"monthly": 0, "season": 0, "birthdays": 0, "freescan": 0, "dormant": 0}


def test_all_new_templates_render():
    for key in ("free_scored", "free_reveal", "free_moved", "free_last", "merchant_quiet",
                "cancel_ending", "winback_30", "winback_90"):
        subject, html, text = emails.render(key, {"first": "Maison", "store_name": "Maison", "ends": "2026-09-30",
                                                  "book": {"count": "212", "latent": "£1.4m", "top": 40, "quiet": 3,
                                                           "baskets": 2, "basket_value": 1500}}, "https://x/u")
        assert subject and "Unsubscribe" in html and text
    s, h, t = emails.render("season_moment", {"first": "Sarah", "moment": {"name": "Gifting appointments", "starts": "2026-11-17",
                                                                            "grades": ["A*", "A"], "template": "Gifting appointment",
                                                                            "note": "Take the gift list off their hands.", "fit": 12}}, "https://x/u")
    assert "12 clients in the book fit it" in h
