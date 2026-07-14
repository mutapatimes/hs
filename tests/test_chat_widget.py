"""Support chat widget (Brevo Conversations): env-driven, off by default, injected before </body>."""
from halia.api.content import chat_widget_snippet, with_chat_widget


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
