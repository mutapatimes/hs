"""The weekly digest: counted deterministically, phrased optionally.

The property worth defending is that the figures are never the model's. `facts()` counts; `write()`
only phrases, and falls back to composing the same numbers itself. So the tests here check the
arithmetic hard and the prose barely at all — and check that the fallback says something true
rather than nothing.
"""
import time

import pytest

from halia import digest
from halia.cache import cache

SHOP = "shopx"
NOW = 1_780_000_000.0          # fixed clock: "the last seven days" must not drift with the suite


@pytest.fixture(autouse=True)
def _clean():
    cache.clear()
    yield
    cache.clear()


def _row(**kw):
    row = {"cid": "c1", "name": "Grace Ladoja", "grade": "A*", "tier": "A1", "known": False,
           "band": "active", "spend": 4200, "latent": 12400, "ordersCount": 3,
           "lastSort": NOW - 2 * 86400}
    row.update(kw)
    return row


def _seed(rows):
    cache.set(SHOP, results=[], payload={"data": rows}, orders=[])


# ── the counting ──────────────────────────────────────────────────────────────
def test_a_cold_book_reports_nothing_rather_than_zeroes(monkeypatch):
    f = digest.facts(SHOP, now=NOW)
    assert f["warm"] is False and f["clients"] == 0


def test_recent_orders_only_counts_top_grade_inside_seven_days():
    _seed([
        _row(cid="a", name="Recent A", lastSort=NOW - 2 * 86400),          # counts
        _row(cid="b", name="Old A", lastSort=NOW - 30 * 86400),            # too long ago
        _row(cid="c", name="Recent B", tier="B", lastSort=NOW - 86400),    # not top grade
        _row(cid="d", name="No date", lastSort=0),                         # never ordered
    ])
    f = digest.facts(SHOP, now=NOW)
    assert f["recent_orders"] == 1
    assert [c["name"] for c in f["recent_top"]] == ["Recent A"]


def test_quiet_clients_are_ranked_by_spend():
    _seed([
        _row(cid="a", name="Big", known=True, spend=90000),
        _row(cid="b", name="Small", known=True, spend=100),
        _row(cid="c", name="Active", band="active"),
    ])
    f = digest.facts(SHOP, now=NOW)
    assert f["quiet"] == 2
    assert [c["name"] for c in f["quiet_top"]] == ["Big", "Small"]


def test_baskets_are_counted_and_totalled():
    _seed([
        _row(cid="a", name="Basket A", cart={"value": 1800}),
        _row(cid="b", name="Basket B", cart={"value": 400}),
        _row(cid="c", name="Empty", cart={"value": 0}),
        _row(cid="d", name="None"),
    ])
    f = digest.facts(SHOP, now=NOW)
    assert f["baskets"] == 2 and f["basket_value"] == 2200
    assert f["basket_top"][0]["name"] == "Basket A"


def test_hidden_and_latent_are_totalled():
    _seed([_row(cid="a", known=False, latent=10000), _row(cid="b", known=True, latent=5000)])
    f = digest.facts(SHOP, now=NOW)
    assert f["hidden"] == 1 and f["latent"] == 15000


def test_names_carried_are_capped():
    """A digest is a briefing, not a mailing list."""
    _seed([_row(cid=str(i), name=f"Quiet {i}", known=True, spend=i * 100) for i in range(20)])
    f = digest.facts(SHOP, now=NOW)
    assert f["quiet"] == 20 and len(f["quiet_top"]) == 3


def test_facts_never_trigger_a_sync(monkeypatch):
    """A briefing is a convenience; it must read the warm book or report nothing."""
    from halia.api import data
    monkeypatch.setattr(data, "results_for", lambda *a, **k: pytest.fail("synced for a digest"))
    digest.facts(SHOP, now=NOW)


# ── the phrasing ──────────────────────────────────────────────────────────────
def test_without_ai_the_digest_still_states_the_facts(monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    _seed([_row(cid="a", name="Grace Ladoja", known=True, spend=9000),
           _row(cid="b", name="Basket", cart={"value": 1800})])
    text, source = digest.write(digest.facts(SHOP, now=NOW))
    assert source == "book"
    assert "Grace Ladoja" in text and "1,800" in text and "quiet" in text


def test_an_empty_week_says_so_plainly(monkeypatch):
    """Every client row raises something (a known one is by definition in the winback play, an
    unknown one counts as quietly valuable), so this branch is for a book with nothing in it."""
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    text, source = digest.write(digest.facts(SHOP, now=NOW))
    assert source == "book" and "Nothing needs your attention" in text


def test_counts_of_one_read_as_english():
    """A briefing that says "1 client are quiet" reads as machine output and undermines the rest."""
    one = digest._plain({"recent_orders": 1, "recent_top": [], "quiet": 1, "quiet_top": [],
                         "baskets": 1, "basket_value": 900, "basket_top": [], "hidden": 1,
                         "campaigns": [{"name": "Spring", "ends": "2026-08-01", "members": 1}]})
    joined = " ".join(one)
    assert "1 top-grade client ordered" in joined
    assert "1 proven client is quiet" in joined
    assert "1 basket is open" in joined
    assert "1 client in it" in joined
    assert "1 client in your book is quietly valuable" in joined
    for wrong in ("1 clients", "1 baskets", "client are", "basket are"):
        assert wrong not in joined


def test_the_model_only_sees_the_figures(monkeypatch):
    """The prompt is the counted facts, never the book: no e-mail, no address, no order line."""
    from halia import llm
    seen = {}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda s, u, **k: seen.update(user=u, system=s) or "Prose.")
    _seed([_row(cid="a", name="Grace Ladoja", email="grace@x.com", known=True, spend=9000)])
    text, source = digest.write(digest.facts(SHOP, now=NOW))
    assert (text, source) == ("Prose.", "ai")
    assert "grace@x.com" not in seen["user"]
    assert "no earlier one to compare" in seen["system"]   # the no-false-trend instruction


def test_a_model_failure_falls_back_to_the_facts(monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: None)
    _seed([_row(cid="a", name="Grace Ladoja", known=True, spend=9000)])
    text, source = digest.write(digest.facts(SHOP, now=NOW))
    assert source == "book" and "Grace Ladoja" in text
