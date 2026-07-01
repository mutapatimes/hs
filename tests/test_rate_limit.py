"""Per-IP rate limiter (pure function; the middleware itself is inert under pytest)."""
from halia.api import app as appmod


def test_write_limit_blocks_after_max():
    appmod._RL_HITS.clear()
    ip = "9.9.9.9"
    for _ in range(appmod._RL_MAX["w"]):
        assert appmod._rate_limited(ip, True) is False
    assert appmod._rate_limited(ip, True) is True          # one past the write limit
    assert appmod._rate_limited("8.8.8.8", True) is False  # a different IP is unaffected


def test_reads_have_a_higher_limit():
    appmod._RL_HITS.clear()
    ip = "7.7.7.7"
    for _ in range(appmod._RL_MAX["r"]):
        assert appmod._rate_limited(ip, False) is False
    assert appmod._rate_limited(ip, False) is True


def test_window_expires():
    appmod._RL_HITS.clear()
    ip = "6.6.6.6"
    for _ in range(appmod._RL_MAX["w"]):
        assert appmod._rate_limited(ip, True, now=1000.0) is False
    assert appmod._rate_limited(ip, True, now=1000.0) is True
    assert appmod._rate_limited(ip, True, now=1000.0 + appmod._RL_WINDOW + 1) is False
