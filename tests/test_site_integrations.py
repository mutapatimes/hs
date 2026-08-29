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
    assert "data-cal" in Path("web/site/contact.html").read_text()
    assert "window.HALIA_CAL" in Path("web/site/static/brand.js").read_text()


def test_demo_is_a_booking_page_not_a_sample_dashboard():
    from pathlib import Path
    demo = Path("web/site/demo.html").read_text()
    assert "Book a demo." in demo and 'id="bookForm"' in demo and "source:'demo'" in demo
    assert "Hidden VICs" not in demo and "__STAT_" not in demo
    home = Path("web/site/index.html").read_text()
    assert "location.href='/demo'" not in home and "Pick a time" in home
    r = TestClient(app).get("/demo")
    assert r.status_code == 200 and "Book a demo." in r.text
