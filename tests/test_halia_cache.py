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
