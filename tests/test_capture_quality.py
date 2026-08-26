"""Clean capture: email typo correction and postcode normalisation, all local."""
from halia import capture_quality as cq


def _no_dns(monkeypatch, answer=True):
    monkeypatch.setattr(cq, "_domain_resolves", lambda d: answer)


# ── email ────────────────────────────────────────────────────────────────────

def test_typo_domains_suggest_the_fix(monkeypatch):
    _no_dns(monkeypatch)
    for raw, want in [("a@gamil.com", "a@gmail.com"), ("b@hotmial.com", "b@hotmail.com"),
                      ("c@outlok.com", "c@outlook.com"), ("d@yaho.com", "d@yahoo.com"),
                      ("e@icoud.com", "e@icloud.com"), ("f@gmail.con", "f@gmail.com")]:
        email, suggestion, _ = cq.clean_email(raw)
        assert suggestion == want, raw


def test_tld_slip_on_any_domain(monkeypatch):
    _no_dns(monkeypatch)
    email, suggestion, _ = cq.clean_email("x@somebrand.con")
    assert suggestion == "x@somebrand.com"


def test_clean_addresses_pass_untouched(monkeypatch):
    _no_dns(monkeypatch)
    email, suggestion, ok = cq.clean_email("  Grace.Ladoja@Gmail.com ")
    assert email == "grace.ladoja@gmail.com" and suggestion is None and ok


def test_dead_domain_flags_not_ok(monkeypatch):
    _no_dns(monkeypatch, answer=False)
    _, suggestion, ok = cq.clean_email("a@zzzz-not-a-real-domain-qq.com")
    assert suggestion is None and ok is False


def test_syntax_garbage(monkeypatch):
    _no_dns(monkeypatch)
    for bad in ("not-an-email", "a@b", "@x.com", ""):
        _, _, ok = cq.clean_email(bad)
        assert ok is False, bad


def test_dns_off_skips_lookup(monkeypatch):
    called = []
    monkeypatch.setattr(cq, "_domain_resolves", lambda d: called.append(d) or True)
    _, _, ok = cq.clean_email("a@anything.org", check_dns=False)
    assert ok and called == []


# ── postcode ─────────────────────────────────────────────────────────────────

def test_uk_postcode_respaced():
    assert cq.clean_postcode("sw1a1aa") == ("SW1A 1AA", True)
    assert cq.clean_postcode(" w1J 7bU ", "United Kingdom") == ("W1J 7BU", True)


def test_uk_outcode_alone_passes():
    assert cq.clean_postcode("SW10") == ("SW10", True)


def test_uk_garbage_flags_invalid():
    _, ok = cq.clean_postcode("12345", "uk")
    assert ok is False


def test_other_countries_pass_through():
    assert cq.clean_postcode("10021", "US") == ("10021", True)
    assert cq.clean_postcode("75008", "France") == ("75008", True)


def test_blank_is_fine():
    assert cq.clean_postcode("") == ("", True)
