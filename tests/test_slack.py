"""Slack alerts: encrypted store round-trip, alert block-building, and the connect/test/
disconnect endpoints + live-dispatch wiring (no network: notify.send_slack is stubbed)."""
import pytest
from fastapi.testclient import TestClient

from halia import notify
from halia.api import realtime, shopify_auth, slack_integration
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

HOOK = "https://hooks.slack.com/services/T000/B000/xyzSECRETtoken"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    yield TestClient(app), store


def _tenant(store, shop="shops"):
    tok = new_token()
    store.create_tenant(shop, "woocommerce", "Shop", hash_token(tok))
    return tok


# ── storage ──────────────────────────────────────────────────────────────────────
def test_store_roundtrips_and_deletes(tmp_path):
    # Stored through crypto.encrypt (ciphertext at rest when HALIA_ENCRYPTION_KEY is set in prod);
    # here we assert the save -> get -> delete contract.
    store = ShopStore(db_path=tmp_path / "s.db")
    store.save_slack("shopx", HOOK)
    assert store.get_slack("shopx")["webhook_url"] == HOOK
    store.delete_slack("shopx")
    assert store.get_slack("shopx") is None


# ── block building ───────────────────────────────────────────────────────────────
def test_build_alert_blocks_shape():
    alert = {"grade": "A*", "name": "Eleanor Ashworth", "order_id": "#1042", "spend": 180,
             "signals": ["Prime postcode (W1)", "Family-office email"]}
    text, blocks = slack_integration.build_alert_blocks(alert, "https://app.halia.test")
    assert "Eleanor Ashworth" in text and "A*" in text
    assert blocks[0]["type"] == "header"
    body = blocks[1]["text"]["text"]
    assert "Eleanor Ashworth" in body and "Prime postcode (W1)" in body
    joined = str(blocks)
    assert "£180" in joined and "#1042" in joined
    assert any(b.get("type") == "actions" for b in blocks)          # "Open in Halia" button
    # No app URL configured -> no button, but still valid text + section.
    _, nb = slack_integration.build_alert_blocks(alert, "")
    assert not any(b.get("type") == "actions" for b in nb)


# ── endpoints ────────────────────────────────────────────────────────────────────
def test_connect_rejects_non_slack_url(client):
    c, store = client
    c.cookies.set(COOKIE, _tenant(store))
    r = c.post("/v1/slack/connect", json={"webhook_url": "https://evil.example.com/x"})
    assert r.status_code == 400 and store.get_slack("shops") is None


def test_connect_status_test_disconnect(client, monkeypatch):
    c, store = client
    sent = []
    monkeypatch.setattr(notify, "send_slack", lambda url, text, blocks=None: (sent.append((url, text)), True)[1])
    c.cookies.set(COOKIE, _tenant(store))

    r = c.post("/v1/slack/connect", json={"webhook_url": HOOK})
    assert r.status_code == 200 and r.json()["ok"]
    assert sent and sent[0][0] == HOOK                      # a hello was posted on connect
    assert store.get_slack("shops")["webhook_url"] == HOOK

    st = c.get("/v1/slack/status").json()
    assert st["connected"] is True and "xyzSECRETtoken" not in st["webhook"]   # masked

    sent.clear()
    assert c.post("/v1/slack/test").json()["ok"] is True
    assert sent and "Eleanor Ashworth" in sent[0][1]

    assert c.post("/v1/slack/disconnect").json()["ok"] is True
    assert store.get_slack("shops") is None
    assert c.get("/v1/slack/status").json()["connected"] is False


def test_connect_reports_failure_when_slack_rejects(client, monkeypatch):
    c, store = client
    monkeypatch.setattr(notify, "send_slack", lambda *a, **k: False)
    c.cookies.set(COOKIE, _tenant(store))
    r = c.post("/v1/slack/connect", json={"webhook_url": HOOK})
    assert r.status_code == 400 and store.get_slack("shops") is None    # not stored on failure


# ── live dispatch ────────────────────────────────────────────────────────────────
def test_dispatch_posts_to_slack_when_connected(client, monkeypatch):
    c, store = client
    store.save_slack("shops", HOOK)
    posted = []
    monkeypatch.setattr(notify, "send_slack",
                        lambda url, text, blocks=None, shop=None: (posted.append(url), True)[1])
    monkeypatch.setattr(notify, "email_configured", lambda: False)      # isolate the Slack path
    alert = {"grade": "A*", "name": "A VIC", "order_id": "#9", "spend": 500, "signals": ["Work email"]}
    realtime._dispatch("shops", alert, {"notify_emails": []})
    assert posted == [HOOK]
