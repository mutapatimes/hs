"""High-value open-basket alerts: gating, RAM de-dup, recency, channels."""
from datetime import date

import halia.api.basket_alerts as ba

TODAY = date(2026, 7, 8)
S = {"notify_grades": ["A*", "A"], "basket_alerts": True}   # channel provided by Slack in _setup


class _FakeStore:
    def __init__(self, slack):
        self._slack = slack

    def get_slack(self, shop):
        return self._slack


def _client(cid, grade, value, started="2026-07-07", bid=None, count=2):
    return {"cid": cid, "name": f"Client {cid}", "grade": grade,
            "cart": {"id": bid or f"chk-{cid}", "value": value, "count": count, "started": started}}


def _setup(monkeypatch, slack={"webhook_url": "https://hooks.slack.com/x"}, email=False):
    sent = []
    monkeypatch.setattr(ba, "shop_store", lambda: _FakeStore(slack))
    monkeypatch.setattr(ba.notify, "send_slack",
                        lambda url, text, blocks=None, shop=None: sent.append(("slack", text)) or True)
    monkeypatch.setattr(ba.notify, "email_configured", lambda: email)
    monkeypatch.setattr(ba.notify, "send_email",
                        lambda to, subj, html, shop=None: sent.append(("email", to)) or True)
    ba._seen.clear()
    return sent


def test_alerts_only_high_value_graded_baskets(monkeypatch):
    sent = _setup(monkeypatch)
    clients = [_client(1, "A*", 1200),   # qualifies
               _client(2, "C", 2000),    # wrong grade
               _client(3, "A", 300),     # below the £500 default threshold
               {"cid": 4, "name": "No cart", "grade": "A*", "cart": None}]  # no basket
    n = ba.dispatch_basket_alerts("shop", clients, S, today=TODAY)
    assert n == 1 and sent == [("slack", "Open basket · Client 1 — £1,200")]


def test_dedup_suppresses_repeats_but_alerts_new(monkeypatch):
    _setup(monkeypatch)
    clients = [_client(1, "A*", 1200)]
    assert ba.dispatch_basket_alerts("shop", clients, S, today=TODAY) == 1
    assert ba.dispatch_basket_alerts("shop", clients, S, today=TODAY) == 0   # same basket -> silent
    clients2 = clients + [_client(9, "A*", 800, bid="chk-9")]
    assert ba.dispatch_basket_alerts("shop", clients2, S, today=TODAY) == 1  # only the new one


def test_converted_basket_is_forgotten(monkeypatch):
    _setup(monkeypatch)
    clients = [_client(1, "A*", 1200)]
    assert ba.dispatch_basket_alerts("shop", clients, S, today=TODAY) == 1
    assert ba.dispatch_basket_alerts("shop", [], S, today=TODAY) == 0        # basket gone -> forgotten
    assert ba.dispatch_basket_alerts("shop", clients, S, today=TODAY) == 1   # reappears -> alerts again


def test_recency_gate_excludes_old_baskets(monkeypatch):
    _setup(monkeypatch)
    clients = [_client(1, "A*", 1200, started="2026-06-20")]   # ~18 days old > 7
    assert ba.dispatch_basket_alerts("shop", clients, S, today=TODAY) == 0


def test_no_channel_means_no_alerts(monkeypatch):
    _setup(monkeypatch, slack=None, email=False)
    assert ba.dispatch_basket_alerts("shop", [_client(1, "A*", 1200)], S, today=TODAY) == 0


def test_toggle_off_disables(monkeypatch):
    _setup(monkeypatch)
    s = {"notify_grades": ["A*"], "basket_alerts": False}
    assert ba.dispatch_basket_alerts("shop", [_client(1, "A*", 1200)], s, today=TODAY) == 0


def test_email_channel_sends_to_every_recipient(monkeypatch):
    sent = _setup(monkeypatch, slack=None, email=True)
    s = {"notify_grades": ["A*", "A"], "basket_alerts": True,
         "notify_emails": ["a@b.com", "c@d.com"]}
    n = ba.dispatch_basket_alerts("shop", [_client(1, "A*", 1200)], s, today=TODAY)
    assert n == 1
    assert [x for x in sent if x[0] == "email"] == [("email", "a@b.com"), ("email", "c@d.com")]
