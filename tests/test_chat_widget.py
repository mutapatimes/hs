"""Marketing-site scripts (Brevo chat + GoatCounter): env-driven, off by default, before </body>."""
from halia.api.content import analytics_snippet, chat_widget_snippet, with_chat_widget, with_site_scripts


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("HALIA_CHAT_WIDGET_ID", raising=False)
    assert chat_widget_snippet() == ""
    html = "<html><body><p>page</p></body></html>"
    assert with_chat_widget(html) == html                       # pages ship clean unconfigured


def test_injected_before_body_close(monkeypatch):
    monkeypatch.setenv("HALIA_CHAT_WIDGET_ID", "abc123")
    out = with_chat_widget("<html><body><p>page</p></body></html>")
    assert "BrevoConversationsID" in out and '"abc123"' in out
    assert out.index("brevo-conversations.js") < out.index("</body>")


def test_widget_id_is_json_escaped(monkeypatch):
    monkeypatch.setenv("HALIA_CHAT_WIDGET_ID", 'x"</script>')
    snippet = chat_widget_snippet()
    assert "</script><" not in snippet.lower().replace(" ", "")  # no breakout past the escape
    assert '\\"' in snippet                                      # the quote arrived escaped


def test_analytics_off_by_default_and_on_with_code(monkeypatch):
    monkeypatch.delenv("HALIA_ANALYTICS_CODE", raising=False)
    assert analytics_snippet() == ""
    monkeypatch.setenv("HALIA_ANALYTICS_CODE", "halia")
    snippet = analytics_snippet()
    assert 'data-goatcounter="https://halia.goatcounter.com/count"' in snippet
    assert "gc.zgo.at/count.js" in snippet


def test_analytics_code_must_be_a_plain_subdomain(monkeypatch):
    monkeypatch.setenv("HALIA_ANALYTICS_CODE", 'halia"><script>alert(1)</script>')
    assert analytics_snippet() == ""                             # anything else ships no script


def test_site_scripts_injects_both(monkeypatch):
    monkeypatch.setenv("HALIA_CHAT_WIDGET_ID", "abc123")
    monkeypatch.setenv("HALIA_ANALYTICS_CODE", "halia")
    out = with_site_scripts("<html><body><p>page</p></body></html>")
    assert "BrevoConversationsID" in out and "goatcounter" in out
    assert out.index("goatcounter") < out.index("</body>")
