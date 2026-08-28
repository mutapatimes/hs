"""End of every calendar month, each seat holder gets their own numbers: contacts, captures,
drafts and links made with Halia, orders after a contact, and where they stand on the team."""
from datetime import datetime, timedelta, timezone

import pytest

from halia import emails, journeys
from halia.api import shopify_auth
from halia.api.tenant_auth import hash_token, new_token
from halia.store import ShopStore, month_key

SHOP = "maison.myshopify.com"


@pytest.fixture()
def st(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "m.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    store.create_tenant(SHOP, "shopify", "Maison", hash_token(new_token()))
    sarah = store.create_seat(SHOP, "Sarah Bloom", hash_token(new_token()), "sarah@m.com")
    browser = store.create_seat(SHOP, "Front desk", hash_token(new_token()))   # no email: no recap
    yield store, sarah, browser


def _recorder():
    sent = []
    def send(to, subject, html, text=None, shop=None):
        sent.append((to, subject, html, text))
        return True
    return sent, send


def test_seat_counters_bucket_by_month(st):
    store, sarah, _ = st
    store.bump_seat_metric(sarah, "drafts")
    store.bump_seat_metric(sarah, "drafts", 2)
    store.bump_seat_metric(sarah, "links", month="2026-07")
    assert store.seat_month_metrics(sarah) == {"drafts": 3}
    assert store.seat_month_metrics(sarah, "2026-07") == {"links": 1}
    assert month_key(datetime(2026, 8, 28, tzinfo=timezone.utc)) == "2026-08"


def test_enrolment_covers_seats_with_an_email_only(st):
    store, sarah, browser = st
    assert journeys.ensure_monthly_enrolments(store=store) == 1
    assert journeys.ensure_monthly_enrolments(store=store) == 0          # idempotent
    assert store.journey_exists("sarah@m.com", "monthly")


def test_recap_sends_on_the_first_with_the_seats_numbers_then_reschedules(st, monkeypatch):
    store, sarah, _ = st
    sent, send = _recorder()
    now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(journeys, "_now", lambda: now)
    journeys.enroll_monthly("sarah@m.com", sarah, SHOP, "Maison", "Sarah", store=store)
    store.bump_seat_metric(sarah, "drafts", 14, month="2026-08")
    store.bump_seat_metric(sarah, "links", 3, month="2026-08")
    monkeypatch.setattr("halia.api.reports.build_report", lambda shop, days, fresh=False: {
        "available": True, "seats": [
            {"id": sarah, "name": "Sarah Bloom", "contacts": 22, "clients": 15, "captures": 4, "captured_top": 2,
             "conversions": 5, "revenue": 8600, "topShare": 0.4},
            {"id": "other", "name": "Omar", "contacts": 30, "clients": 20, "captures": 1, "captured_top": 0,
             "conversions": 6, "revenue": 12000, "topShare": 0.2}],
        "totals": {"contacts": 52, "revenue": 20600}})
    journeys.run_due(now=datetime(2026, 8, 31, 23, tzinfo=timezone.utc), send=send, store=store)
    assert sent == []                                                    # the month is not over
    journeys.run_due(now=datetime(2026, 9, 1, 7, tzinfo=timezone.utc), send=send, store=store)
    assert len(sent) == 1
    to, subject, html, text = sent[0]
    assert to == "sarah@m.com" and subject == "Your August with Halia at Maison"
    assert "Hello Sarah," in html and "22 contacts with 15 clients" in html and "captured 4 new" in html
    assert "£8,600" in html and ">14<" in html and ">3<" in html and "40%" in html
    assert "number 2 of 2 on the team" in html
    # nothing until the next first of the month
    journeys.run_due(now=datetime(2026, 9, 20, 7, tzinfo=timezone.utc), send=send, store=store)
    assert len(sent) == 1
    journeys.run_due(now=datetime(2026, 10, 1, 7, tzinfo=timezone.utc), send=send, store=store)
    assert len(sent) == 2 and sent[1][1] == "Your September with Halia at Maison"


def test_quiet_month_gets_the_nudge_and_a_revoked_seat_stops(st, monkeypatch):
    store, sarah, _ = st
    sent, send = _recorder()
    monkeypatch.setattr(journeys, "_now", lambda: datetime(2026, 8, 20, tzinfo=timezone.utc))
    journeys.enroll_monthly("sarah@m.com", sarah, SHOP, "Maison", "Sarah", store=store)
    monkeypatch.setattr("halia.api.reports.build_report", lambda shop, days, fresh=False: {
        "available": True, "seats": [{"id": sarah, "name": "Sarah Bloom", "contacts": 0, "clients": 0,
                                       "captures": 0, "conversions": 0, "revenue": 0}], "totals": {}})
    journeys.run_due(now=datetime(2026, 9, 1, 7, tzinfo=timezone.utc), send=send, store=store)
    assert len(sent) == 1 and "August was quiet on Halia" in sent[0][2]
    store.revoke_seat(SHOP, sarah)
    journeys.run_due(now=datetime(2026, 10, 1, 7, tzinfo=timezone.utc), send=send, store=store)
    assert len(sent) == 1                                                # finished, not resent
    assert store.due_journeys("2099-01-01T00:00:00+00:00") == []


def test_recap_email_renders_in_the_shared_layout():
    subject, html, text = emails.render("monthly_seat", {"first": "Sarah", "store_name": "Maison",
        "recap": {"month_name": "August", "contacts": 3, "clients": 3, "captures": 1, "conversions": 1,
                  "revenue": 1200, "drafts": 5, "links": 1, "remembered": 2, "rank": 1, "team_size": 3,
                  "top_share": 0.67}}, "https://x/u")
    assert subject == "Your August with Halia at Maison"
    assert "Details remembered" in html and "number 1 of 3" in html and "Unsubscribe" in html
    assert "Drafted with Halia: 5" in text
