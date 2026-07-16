"""Shopify Flow integration: the tag vocabulary, and the opt-in auto-push diff on sync."""
import pytest

from halia.api import shopify_push as sp


def _row(**kw):
    base = {"cid": "gid://shopify/Customer/1", "tier": "A1", "grade": "A*",
            "band": "lapsed", "known": False, "ordersCount": 0}
    base.update(kw)
    return base


# ---------------------------------------------------------------- vocabulary
def test_grade_tags_only_for_a_tiers():
    assert "Halia:A*" in sp.play_tags(_row(tier="A1", grade="A*"))
    assert "Halia:A" in sp.play_tags(_row(tier="A", grade="A"))
    assert not any(t.startswith("Halia:B") for t in sp.play_tags(_row(tier="B", grade="B")))


def test_gone_quiet_rules():
    assert sp.PLAY_TAG_GONE_QUIET in sp.play_tags(_row(known=True, band="cooling"))     # proven client
    assert sp.PLAY_TAG_GONE_QUIET in sp.play_tags(_row(ordersCount=3, band="lapsed"))   # lapsed A-tier
    assert sp.PLAY_TAG_GONE_QUIET not in sp.play_tags(_row(ordersCount=1, band="lapsed"))
    assert sp.PLAY_TAG_GONE_QUIET not in sp.play_tags(_row(tier="B", grade="B", ordersCount=3, band="lapsed"))


def test_fresh_rules():
    assert sp.PLAY_TAG_FRESH in sp.play_tags(_row(band="active"))
    assert sp.PLAY_TAG_FRESH in sp.play_tags(_row(band="new"))
    assert sp.PLAY_TAG_FRESH not in sp.play_tags(_row(known=True, band="active"))       # known = protect


def test_desired_tag_map_skips_rows_without_cid():
    payload = {"data": [_row(cid=""), _row(cid="123", band="active")]}
    m = sp.desired_tag_map(payload)
    assert list(m) == ["123"] and sp.PLAY_TAG_FRESH in m["123"]


# ---------------------------------------------------------------- auto-push
class _Sink:
    def __init__(self):
        self.tagged, self.untagged = [], []
    def tag_customer(self, cid, tags):
        self.tagged.append((cid, list(tags)))
    def untag_customer(self, cid, tags):
        self.untagged.append((cid, list(tags)))


@pytest.fixture
def wired(monkeypatch):
    """maybe_auto_push with settings on, billing paid, and a recording stub sink."""
    sink = _Sink()
    import halia.api.settings as st
    import halia.api.billing as bl
    monkeypatch.setattr(st, "settings_for", lambda shop: {"shopify_auto_push": True})
    monkeypatch.setattr(bl, "is_paid", lambda shop: True)
    import halia.adapters.shopify_sink as sk
    monkeypatch.setattr(sk, "ShopifySink", lambda transport=None: sink)
    import scoring.shopify_fetch as sf
    monkeypatch.setattr(sf, "http_transport", lambda shop, token: None)
    from halia.api import data
    monkeypatch.setattr(data, "record_activity", lambda *a, **k: None)
    return sink


def _entry(rows):
    return {"payload": {"data": rows}}


def test_first_sync_pushes_everything(wired):
    sp.maybe_auto_push("s.myshopify.com", "tok", _entry([_row(cid="1", band="active")]), None)
    assert wired.tagged == [("1", ["Halia:A*", "Halia:Fresh"])]
    assert wired.untagged == []


def test_second_sync_only_writes_transitions(wired):
    prev = _entry([_row(cid="1", band="active"), _row(cid="2", known=True, band="cooling")])
    # customer 1 goes quiet (fresh -> gone quiet); customer 2 unchanged
    now = _entry([_row(cid="1", ordersCount=3, band="lapsed"), _row(cid="2", known=True, band="cooling")])
    sp.maybe_auto_push("s.myshopify.com", "tok", now, prev)
    assert wired.tagged == [("1", [sp.PLAY_TAG_GONE_QUIET])]
    assert wired.untagged == [("1", [sp.PLAY_TAG_FRESH])]


def test_customer_leaving_the_surface_loses_play_tags(wired):
    prev = _entry([_row(cid="9", known=True, band="lapsed")])
    sp.maybe_auto_push("s.myshopify.com", "tok", _entry([]), prev)
    assert wired.untagged == [("9", [sp.PLAY_TAG_GONE_QUIET])]
    assert wired.tagged == []


def test_setting_off_writes_nothing(wired, monkeypatch):
    import halia.api.settings as st
    monkeypatch.setattr(st, "settings_for", lambda shop: {"shopify_auto_push": False})
    sp.maybe_auto_push("s.myshopify.com", "tok", _entry([_row(cid="1")]), None)
    assert wired.tagged == [] and wired.untagged == []


def test_unpaid_tenant_writes_nothing(wired, monkeypatch):
    import halia.api.billing as bl
    monkeypatch.setattr(bl, "is_paid", lambda shop: False)
    sp.maybe_auto_push("s.myshopify.com", "tok", _entry([_row(cid="1")]), None)
    assert wired.tagged == []


def test_cap_and_sink_failure_never_raise(wired, monkeypatch):
    monkeypatch.setattr(sp, "AUTO_PUSH_CAP", 2)
    rows = [_row(cid=str(i), band="active") for i in range(5)]
    def boom(cid, tags):
        raise RuntimeError("shopify down")
    wired.tag_customer = boom
    sp.maybe_auto_push("s.myshopify.com", "tok", _entry(rows), None)   # must not raise
