"""RAM-only results cache: set/get/evict + TTL expiry."""
import time

from halia.cache import ResultsCache


def test_set_get_evict():
    c = ResultsCache(ttl=100)
    c.set("shop", results=[1, 2], payload={"p": 1}, orders=[{"order_id": "o"}])
    entry = c.get("shop")
    assert entry["results"] == [1, 2] and entry["payload"] == {"p": 1}
    assert entry["orders"][0]["order_id"] == "o"
    c.evict("shop")
    assert c.get("shop") is None


def test_ttl_expiry():
    c = ResultsCache(ttl=0)  # expires immediately
    c.set("shop", [], {}, [])
    time.sleep(0.01)
    assert c.get("shop") is None


def test_missing_shop():
    assert ResultsCache().get("nobody") is None


def test_a_book_is_released_an_hour_after_its_last_use_and_warm_checks_are_not_use():
    """The published policy: held while the store is in use, released within an hour of the last
    use. A page read extends the idle window; the warm-up's peek never does; past the TTL the book
    is served stale once (get_stale) and get() answers None so a refresh is started."""
    c = ResultsCache(ttl=100, idle=0.05)
    c.set("shop", [1], {"p": 1}, [])
    assert c.peek("shop") == "fresh"
    time.sleep(0.03); assert c.get("shop") is not None          # a use, inside the window
    time.sleep(0.03); assert c.get("shop") is not None          # the window moved with the use
    time.sleep(0.06); assert c.peek("shop") is None             # idle an hour (scaled): gone
    assert c.get("shop") is None and c.get_stale("shop") is None
    c.set("shop", [1], {"p": 1}, [])
    time.sleep(0.03); assert c.peek("shop") == "fresh"          # a peek…
    time.sleep(0.03); assert c.peek("shop") is None             # …did not keep it alive
    s = ResultsCache(ttl=0, idle=100)
    s.set("shop", [1], {"p": 1}, [])
    time.sleep(0.01)
    assert s.get("shop") is None and s.peek("shop") == "stale" and s.get_stale("shop") is not None
