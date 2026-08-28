"""The site's contact surfaces read one config: chat id, Cal.com link, WhatsApp number."""
from fastapi.testclient import TestClient

from halia.api.app import app


def test_chat_config_is_empty_until_configured(monkeypatch):
    for k in ("HALIA_BREVO_CHAT_ID", "HALIA_CAL_LINK", "HALIA_WHATSAPP"):
        monkeypatch.delenv(k, raising=False)
    assert TestClient(app).get("/v1/chat-config").json() == {"id": "", "cal": "", "whatsapp": ""}


def test_chat_config_cleans_the_values(monkeypatch):
    monkeypatch.setenv("HALIA_CAL_LINK", "/halia/walkthrough/")
    monkeypatch.setenv("HALIA_WHATSAPP", "+44 7700 900 123")
    d = TestClient(app).get("/v1/chat-config").json()
    assert d["cal"] == "halia/walkthrough" and d["whatsapp"] == "447700900123"


def test_pages_carry_the_booking_hook():
    from pathlib import Path
    for page in ("web/site/index.html", "web/site/contact.html"):
        assert "data-cal" in Path(page).read_text()
