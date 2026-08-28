"""Browser-extension API: per-tenant token + single-customer grade lookup (zero-retention)."""
import pytest
from fastapi.testclient import TestClient

from halia.api import extension, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.cache import cache
from halia.store import ShopStore

SHOP = "shopx"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "e.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "woocommerce", "Shop X", hash_token(tok))
    cache.clear()
    yield TestClient(app), store, tok
    cache.clear()


def _row(**kw):
    row = {"cid": "c1", "name": "Grace Ladoja", "email": "grace@x.com",
           "phone": "+44 7700 900123", "grade": "A*", "tier": "A1", "score": 98,
           "band": "lapsed", "known": True, "latent": "£12,400", "spend": 4200,
           "ordersCount": 3, "reco": "Lead with service.",
           "signals": [{"seg": "work", "d": "Work email: Goldman Sachs", "x": ""}],
           "adminUrl": "https://shopx/wp-admin/user-edit.php?user_id=1"}
    row.update(kw)
    return row


def _seed(rows):
    cache.set(SHOP, results=[], payload={"data": rows}, orders=[])


# ── token minting ───────────────────────────────────────────────────────────
def test_mint_returns_token_and_status_flips(env):
    client, store, tok = env
    assert client.get("/v1/extension/token", cookies={COOKIE: tok}).json()["enabled"] is False
    r = client.post("/v1/extension/token", cookies={COOKIE: tok})
    assert r.status_code == 200
    raw = r.json()["token"]
    assert raw and store.shop_for_extension_token(hash_token(raw)) == SHOP
    assert client.get("/v1/extension/token", cookies={COOKIE: tok}).json()["enabled"] is True


def test_mint_rotation_replaces_the_old_token(env):
    client, store, tok = env
    first = client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]
    second = client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]
    assert first != second
    assert store.shop_for_extension_token(hash_token(first)) is None
    assert store.shop_for_extension_token(hash_token(second)) == SHOP


# ── lookup auth ───────────────────────────────────────────────────────────────
def test_lookup_rejects_missing_or_bad_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/lookup", json={"email": "a@b.com"}).status_code == 401
    assert client.post("/v1/extension/lookup", json={"email": "a@b.com"},
                       headers={"X-Halia-Ext-Token": "nope"}).status_code == 401


def test_lookup_needs_an_identity(env):
    client, store, tok = env
    ext = client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]
    r = client.post("/v1/extension/lookup", json={}, headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 422


# ── lookup matching ───────────────────────────────────────────────────────────
def _ext_token(client, tok):
    return client.post("/v1/extension/token", cookies={COOKIE: tok}).json()["token"]


def test_lookup_by_email_returns_grade_reasons_latent_play_templates(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/lookup", json={"email": "GRACE@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["found"] is True
    assert d["grade"] == "A*" and d["latent"] == "£12,400"
    assert d["play"] == "sleeping" and d["playLabel"] == "Gone quiet"
    assert "Work email: Goldman Sachs" in d["reasons"]
    assert d["templates"] and "{first_name}" not in d["templates"][0]["body"]
    assert d["adminUrl"].startswith("https://shopx")


def test_lookup_by_cid_and_gid_forms(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(cid="gid://shopify/Customer/555")])
    for ident in ("555", "gid://shopify/Customer/555"):
        d = client.post("/v1/extension/lookup", json={"cid": ident},
                        headers={"X-Halia-Ext-Token": ext}).json()
        assert d["found"] is True and d["grade"] == "A*"


def test_lookup_by_phone_matches_on_national_digits(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/lookup", json={"phone": "07700900123"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["found"] is True and d["name"] == "Grace Ladoja"


def test_lookup_surfaces_last_order_and_open_basket(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(last="Mar 2026",
                cart={"value": 1800, "count": 2, "started": 1, "items": [], "url": "https://x/co"})])
    d = client.post("/v1/extension/lookup", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["last"] == "Mar 2026"
    assert d["cart"] == {"value": 1800, "count": 2, "url": "https://x/co"}


def test_lookup_ignores_empty_basket(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(cart={"value": 0, "count": 0})])
    d = client.post("/v1/extension/lookup", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["cart"] is None


def test_lookup_fresh_play_for_active_hidden_vic(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(known=False, band="active", tier="B", grade="B")])
    d = client.post("/v1/extension/lookup", json={"email": "grace@x.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["play"] == "fresh" and d["hidden"] is True


def test_lookup_unknown_customer_is_not_found(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/lookup", json={"email": "stranger@nowhere.com"},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d == {"found": False}


# ── standing toolbar context ──────────────────────────────────────────────────
def test_context_requires_token(env):
    client, store, tok = env
    assert client.get("/v1/extension/context").status_code == 401
    assert client.get("/v1/extension/context",
                      headers={"X-Halia-Ext-Token": "nope"}).status_code == 401


def test_context_returns_templates_and_running_campaigns(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    import json as _json
    store.save_campaign("camp_now", SHOP, "Spring Preview", "2000-01-01", "2999-01-01",
                        _json.dumps({"tiers": [], "signals": [], "members": ["a", "b"]}))
    store.save_campaign("camp_old", SHOP, "Old Sale", "2000-01-01", "2000-02-01",
                        _json.dumps({"tiers": [], "signals": [], "members": []}))
    d = client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": ext}).json()
    # templates keep {first_name} for the toolbar to fill per client
    assert d["templates"] and any("{first_name}" in t["body"] for t in d["templates"])
    running = [c for c in d["campaigns"] if c["running"]]
    assert [c["id"] for c in running] == ["camp_now"]
    now = next(c for c in d["campaigns"] if c["id"] == "camp_now")
    assert now["utm"] == "spring-preview" and now["members"] == 2
    assert d["campaigns"][0]["id"] == "camp_now"  # running sorts first


# ── product search / cart builder ─────────────────────────────────────────────
def test_products_requires_token_and_is_shopify_only(env):
    client, store, tok = env  # woo tenant, no Shopify admin token
    assert client.get("/v1/extension/products").status_code == 401
    ext = _ext_token(client, tok)
    d = client.get("/v1/extension/products?q=scarf", headers={"X-Halia-Ext-Token": ext}).json()
    assert d == {"products": [], "cart_base": None}


# ── inbox triage batch ────────────────────────────────────────────────────────
def test_batch_grades_known_emails_and_omits_others(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(email="grace@x.com", known=False, band="lapsed", tier="A1"),
           _row(cid="c2", email="ben@x.com", grade="B", tier="B", known=False, band="active")])
    d = client.post("/v1/extension/batch",
                    json={"emails": ["GRACE@x.com", "ben@x.com", "stranger@nowhere.com"]},
                    headers={"X-Halia-Ext-Token": ext}).json()
    g = d["grades"]
    assert set(g) == {"grace@x.com", "ben@x.com"}         # unknown omitted
    assert g["grace@x.com"]["grade"] == "A*" and g["ben@x.com"]["grade"] == "B"
    assert g["ben@x.com"]["play"] == "fresh"


def test_batch_grades_by_name_for_whatsapp_list(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(name="Tarek Bensaime", email="t@x.com", tier="A1")])
    d = client.post("/v1/extension/batch", json={"names": ["Tarek Bensaime", "Nobody"]},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert set(d["grades"]) == {"tarek bensaime"}
    assert d["grades"]["tarek bensaime"]["grade"] == "A*"


def test_batch_is_warm_only_and_needs_a_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/batch", json={"emails": ["a@b.com"]}).status_code == 401
    ext = _ext_token(client, tok)  # no cache seeded -> warm miss returns empty, never syncs
    d = client.post("/v1/extension/batch", json={"emails": ["a@b.com"]},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d == {"grades": {}}


# ── one-click actions ─────────────────────────────────────────────────────────
def test_action_requires_token_and_cid(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    assert client.post("/v1/extension/action", json={"action": "pipeline", "cid": "1"}).status_code == 401
    assert client.post("/v1/extension/action", json={"action": "pipeline"},
                       headers={"X-Halia-Ext-Token": ext}).status_code == 422


def test_action_campaign_add_appends_member(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    import json as _json
    store.save_campaign("camp1", SHOP, "Spring", "2025-03-01", "2025-05-31",
                        _json.dumps({"tiers": [], "signals": [], "members": []}))
    r = client.post("/v1/extension/action",
                    json={"action": "campaign_add", "campaign_id": "camp1", "cid": "c9"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200 and r.json()["count"] == 1
    got = _json.loads(store.get_campaign("camp1", SHOP)["config_json"])
    assert got["members"] == ["c9"]
    # idempotent: adding again does not duplicate
    client.post("/v1/extension/action",
                json={"action": "campaign_add", "campaign_id": "camp1", "cid": "c9"},
                headers={"X-Halia-Ext-Token": ext})
    got2 = _json.loads(store.get_campaign("camp1", SHOP)["config_json"])
    assert got2["members"] == ["c9"]


def test_action_pipeline_needs_shopify_writeback(env):
    client, store, tok = env  # SHOP is a woocommerce tenant here
    ext = _ext_token(client, tok)
    r = client.post("/v1/extension/action", json={"action": "pipeline", "cid": "c1"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 400  # pipeline is Shopify-write-back only


def test_action_note_requires_text_and_shopify(env):
    client, store, tok = env  # woo tenant
    ext = _ext_token(client, tok)
    # empty note -> 422 (checked before the Shopify sink)
    assert client.post("/v1/extension/action", json={"action": "note", "cid": "c1", "note": "  "},
                       headers={"X-Halia-Ext-Token": ext}).status_code == 422
    # real note on a non-Shopify tenant -> 400 (write-back only)
    assert client.post("/v1/extension/action",
                       json={"action": "note", "cid": "c1", "note": "Prefers navy"},
                       headers={"X-Halia-Ext-Token": ext}).status_code == 400


def test_context_carries_team_todos(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(cid="q1", name="Grace", known=True, band="lapsed", tier="A1")])  # gone quiet -> todo
    d = client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": ext}).json()
    assert "todos" in d and "slack" in d
    assert any(t["kind"] == "gone_quiet" and t["cid"] == "q1" for t in d["todos"])


def test_action_contacted_records_and_reports(env, monkeypatch):
    client, store, tok = env  # woo tenant: Shopify record fails, but the action still succeeds
    ext = _ext_token(client, tok)
    r = client.post("/v1/extension/action",
                    json={"action": "contacted", "cid": "c1", "client_name": "Grace",
                          "reason": "Sent a note", "actor": "Sarah"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True and j["recorded"] is False and j["slack"] is False


def test_action_contacted_broadcasts_to_slack_when_connected(env, monkeypatch):
    client, store, tok = env
    ext = _ext_token(client, tok)
    store.save_slack(SHOP, "https://hooks.slack.com/services/xxx")
    sent = {}
    import halia.notify as notify
    monkeypatch.setattr(notify, "send_slack", lambda url, text, *a, **k: sent.update(url=url, text=text) or True)
    r = client.post("/v1/extension/action",
                    json={"action": "contacted", "cid": "c1", "client_name": "Grace",
                          "reason": "Called", "actor": "Sarah"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.json()["slack"] is True
    assert "Sarah contacted Grace" in sent["text"] and "Called" in sent["text"]


def test_action_rejects_unknown(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    r = client.post("/v1/extension/action", json={"action": "wat", "cid": "c1"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 422


# ── proactive radar events ────────────────────────────────────────────────────
def test_events_requires_token_and_returns_recent_alerts(env):
    client, store, tok = env
    assert client.get("/v1/extension/events").status_code == 401
    ext = _ext_token(client, tok)
    assert client.get("/v1/extension/events", headers={"X-Halia-Ext-Token": ext}).json() == {"events": []}
    cache.add_alert(SHOP, {"order_id": "o9", "name": "Grace", "grade": "A*", "spend": 1689,
                           "signals": ["Work email"], "when": "2026-07-20T09:00:00"})
    d = client.get("/v1/extension/events", headers={"X-Halia-Ext-Token": ext}).json()
    assert d["events"][-1]["order_id"] == "o9" and d["events"][-1]["spend"] == 1689


# ── last-contacted cue ────────────────────────────────────────────────────────
def test_history_requires_token_and_is_null_off_shopify(env):
    client, store, tok = env  # woo tenant: no shared metafield
    assert client.get("/v1/extension/history?cid=c1").status_code == 401
    ext = _ext_token(client, tok)
    d = client.get("/v1/extension/history?cid=c1", headers={"X-Halia-Ext-Token": ext}).json()
    assert d == {"last_contact": None}


def test_last_outreach_picks_the_most_recent_contact():
    acts = [
        {"action": "added", "actor_name": "Sys", "at": "2026-07-01T09:00:00"},
        {"action": "note", "actor_name": "Ben", "at": "2026-07-05T09:00:00", "note": "Prefers navy"},
        {"action": "contacted", "actor_name": "Sarah", "at": "2026-07-10T09:00:00", "note": "Called"},
    ]
    last = extension._last_outreach(acts)
    assert last["by"] == "Sarah" and last["action"] == "contacted" and last["note"] == "Called"
    assert extension._last_outreach([{"action": "added", "at": "x"}]) is None
    assert extension._last_outreach([]) is None


# ── draft ("Draft with Halia") ─────────────────────────────────────────────────
def _draft(client, ext, body):
    return client.post("/v1/extension/draft", json=body, headers={"X-Halia-Ext-Token": ext})


def test_draft_requires_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/draft", json={"email": "a@b.com"}).status_code == 401


def test_draft_uses_ai_when_available(env, monkeypatch):
    from halia import llm
    seen = {}
    monkeypatch.setattr(llm, "available", lambda: True)

    def fake_complete(system, user, **kw):
        seen["system"], seen["user"], seen["model"] = system, user, kw.get("model")
        return "Dear Grace, lovely to hear from you."
    monkeypatch.setattr(llm, "complete", fake_complete)

    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _draft(client, ext, {"email": "grace@x.com",
                             "thread": [{"from": "them", "text": "Is the coat back in stock?"}]}).json()
    assert d["source"] == "ai"
    assert d["draft"] == "Dear Grace, lovely to hear from you."
    assert d["found"] is True and d["grade"] == "A*"
    # the client's live standing and the visible thread are both in the prompt
    assert "Goldman Sachs" in seen["user"] and "coat back in stock" in seen["user"]
    assert store.shop_metric(SHOP, "extension_draft_ai") == 1


def test_draft_falls_back_to_template_without_ai(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _draft(client, ext, {"email": "grace@x.com"}).json()
    assert d["source"] == "template"
    assert d["draft"] and "{first_name}" not in d["draft"]
    assert d["ai_available"] is False
    assert store.shop_metric(SHOP, "extension_draft_ai") == 0


def test_draft_ai_failure_falls_back_to_template(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: None)   # model call failed
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _draft(client, ext, {"email": "grace@x.com"}).json()
    assert d["source"] == "template" and d["draft"]
    assert store.shop_metric(SHOP, "extension_draft_ai") == 0


def test_draft_respects_weekly_cap(env, monkeypatch):
    from halia import llm
    called = {"n": 0}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "AI")
    monkeypatch.setattr(extension.config, "LLM_WEEKLY_CAP", 1)
    client, store, tok = env
    store.bump_metric(SHOP, "extension_draft_ai", 1)             # cap already reached
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _draft(client, ext, {"email": "grace@x.com"}).json()
    assert d["source"] == "template" and called["n"] == 0        # AI never called past the cap


def test_draft_premium_model_for_a_tier(env, monkeypatch):
    from halia import llm
    picked = {}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda s, u, **k: picked.__setitem__("m", k.get("model")) or "x")
    monkeypatch.setattr(extension.config, "LLM_MODEL_PREMIUM", "premium-model")
    monkeypatch.setattr(extension.config, "LLM_MODEL", "cheap-model")
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])                                             # A* / tier A1
    _draft(client, ext, {"email": "grace@x.com"})
    assert picked["m"] == "premium-model"
    _seed([_row(cid="c2", email="b@x.com", grade="B", tier="B", known=False, band="active")])
    _draft(client, ext, {"email": "b@x.com"})
    assert picked["m"] == "cheap-model"                        # non-A tier stays on the cheap model


def test_draft_works_for_unknown_client(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _draft(client, ext, {"email": "stranger@nowhere.com"}).json()
    assert d["found"] is False and d["draft"]                  # still returns a usable template draft


def test_draft_context_includes_gone_quiet_standing(env):
    ctx = extension._draft_context(
        SHOP,
        {"found": True, "name": "Grace", "grade": "A*", "tier": "A1", "play": "sleeping",
         "reasons": ["Work email: Goldman Sachs"], "action": "Reach out personally."},
        "whatsapp",
        [{"from": "them", "text": "hi"}],
        "welcome her back")
    assert "gone quiet" in ctx and "Goldman Sachs" in ctx
    assert "welcome her back" in ctx and "Client: hi" in ctx


def test_clean_thread_caps_and_normalises():
    raw = [{"from": "client", "text": "a"}, {"from": "me", "text": "b"}] * 5
    out = extension._clean_thread(raw)
    assert len(out) == 6 and out[0]["from"] in ("them", "me")
    assert extension._clean_thread("nope") == []
    assert extension._clean_thread([{"from": "them", "text": "  "}]) == []   # blank dropped


# ── brief (read the thread, recommend a reply and the next moves) ─────────────
def _brief(client, ext, body):
    return client.post("/v1/extension/brief", json=body, headers={"X-Halia-Ext-Token": ext})


_AI_BRIEF = {"summary": "She asked about the tan coat and has gone quiet since March.",
             "reply": "Hello Grace, the tan coat is back in your size.",
             "urgency": "today", "language": "en", "english": "",
             "actions": [{"kind": "pipeline", "label": "Add to your list", "why": "Proven, quiet."},
                         {"kind": "advice", "label": "Mention the trunk show", "why": "She attends."}]}


def test_brief_requires_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/brief", json={"email": "a@b.com"}).status_code == 401


def test_brief_uses_ai_and_reads_the_thread(env, monkeypatch):
    from halia import llm
    seen = {}
    monkeypatch.setattr(llm, "available", lambda: True)

    def fake_structured(system, user, schema, **kw):
        seen["user"], seen["schema"], seen["model"] = user, schema, kw.get("model")
        return _AI_BRIEF
    monkeypatch.setattr(llm, "structured", fake_structured)

    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _brief(client, ext, {"email": "grace@x.com", "channel": "whatsapp",
                             "thread": [{"from": "them", "text": "Is the tan coat back?"},
                                        {"from": "me", "text": "Let me check."}]}).json()
    assert d["source"] == "ai"
    assert d["summary"] == _AI_BRIEF["summary"] and d["reply"] == _AI_BRIEF["reply"]
    assert d["urgency"] == "today" and len(d["actions"]) == 2
    assert d["read_thread"] == 2 and d["found"] is True and d["grade"] == "A*"
    # the client's standing and both sides of the conversation reach the prompt
    assert "Goldman Sachs" in seen["user"] and "tan coat" in seen["user"] and "Let me check" in seen["user"]
    assert seen["schema"]["required"] == ["summary", "reply", "urgency", "language", "english", "actions"]
    assert d["language"] == "en" and d["english"] is None
    assert store.shop_metric(SHOP, "extension_brief_ai") == 1


def test_brief_without_ai_falls_back_to_the_book(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _brief(client, ext, {"email": "grace@x.com"}).json()
    assert d["source"] == "book" and d["ai_available"] is False
    assert "Grace Ladoja" in d["summary"] and "gone quiet" in d["summary"]
    assert d["reply"] and "{first_name}" not in d["reply"]
    assert [a["kind"] for a in d["actions"]]                       # heuristic actions still offered
    assert store.shop_metric(SHOP, "extension_brief_ai") == 0


def test_brief_ai_failure_falls_back(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: None)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _brief(client, ext, {"email": "grace@x.com"}).json()
    assert d["source"] == "book" and d["summary"] and d["reply"]


def test_brief_respects_weekly_cap(env, monkeypatch):
    from halia import llm
    called = {"n": 0}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or _AI_BRIEF)
    monkeypatch.setattr(extension.config, "LLM_WEEKLY_CAP", 1)
    client, store, tok = env
    store.bump_metric(SHOP, "extension_brief_ai", 1)               # cap already reached
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _brief(client, ext, {"email": "grace@x.com"}).json()
    assert d["source"] == "book" and called["n"] == 0


def test_brief_suggests_a_running_campaign(env, monkeypatch):
    import json as _json
    from datetime import date, timedelta
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    today = date.today()
    store.save_campaign("c-1", SHOP, "Spring Preview", str(today - timedelta(days=1)),
                        str(today + timedelta(days=7)), _json.dumps({"members": []}))
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _brief(client, ext, {"email": "grace@x.com"}).json()
    assert d["campaign"]["name"] == "Spring Preview"               # wired for the one-click action
    assert any(a["kind"] == "campaign" for a in d["actions"])


def test_brief_handles_an_unknown_person(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _brief(client, ext, {"email": "stranger@nowhere.com"}).json()
    assert d["found"] is False and d["summary"] and d["reply"]
    assert d["actions"] == []                                      # nothing to act on for a stranger


def test_summary_and_actions_from_the_book():
    row = {"found": True, "name": "Grace Ladoja", "grade": "A*", "play": "sleeping",
           "ordersCount": 3, "last": "Mar 2026", "cart": {"value": 1800}}
    s = extension._summary_of(row, {"by": "Sarah"})
    assert "Grace Ladoja" in s and "gone quiet" in s and "3 orders" in s
    assert "basket open" in s and "already contacted by Sarah" in s
    acts = extension._suggested_actions(row, {"id": "c1", "name": "Spring"}, {"by": "Sarah"})
    kinds = [a["kind"] for a in acts]
    assert "pipeline" in kinds and "campaign" in kinds
    assert "contacted" not in kinds                                # already logged, don't re-suggest
    assert extension._suggested_actions({"found": False}, None, None) == []


# ── unit helpers ──────────────────────────────────────────────────────────────
def test_play_of_rules():
    assert extension._play_of({"known": True}) == "sleeping"
    assert extension._play_of({"tier": "A", "ordersCount": 2, "band": "lapsed"}) == "sleeping"
    assert extension._play_of({"band": "active"}) == "fresh"
    assert extension._play_of({"band": "new"}) == "fresh"
    assert extension._play_of({"band": "cooling"}) == ""


def test_digits_takes_trailing_national_part():
    assert extension._digits("+44 7700 900123") == extension._digits("07700900123")
    assert extension._digits("123") == "123"  # too short to compare, returned as-is


def test_e164_only_trusts_international_numbers():
    assert extension._e164("+44 7700 900123") == "447700900123"
    assert extension._e164("0044 7700 900123") == "447700900123"    # 00 international prefix
    assert extension._e164("07700 900123") == ""                    # bare local: can't match E.164
    assert extension._e164("") == "" and extension._e164(None) == ""


# ── today (iOS widget / App Intents queue) ───────────────────────────────────
def test_today_requires_token(env):
    client, store, tok = env
    assert client.get("/v1/extension/today").status_code == 401


def test_today_returns_reach_queue(env):
    import time
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row(cid="c1", name="Amelia Hart", tier="A1", grade="A*", band="active",
                lastSort=time.time())])
    r = client.get("/v1/extension/today", headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200
    j = r.json()
    assert j["count"] >= 1 and j["label"] == "Shop X"
    todo = j["todos"][0]
    assert todo["name"] == "Amelia Hart" and todo["cid"] == "c1"
    assert todo["kind"] in ("new_order", "gone_quiet")


# ── directory (iOS CallKit VIP caller-ID) ────────────────────────────────────
def test_directory_requires_token(env):
    client, store, tok = env
    assert client.get("/v1/extension/directory").status_code == 401


def test_directory_labels_sorts_and_skips_local(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([
        _row(cid="c1", name="Amelia Hart", grade="A*", phone="+44 7700 900500"),
        _row(cid="c2", name="James Fenn", grade="A", phone="+1 (212) 555-0100"),
        _row(cid="c3", name="Local Only", grade="B", phone="07700 900999"),   # no country code
    ])
    r = client.get("/v1/extension/directory", headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200
    entries = r.json()["entries"]
    labels = [e["label"] for e in entries]
    assert "Amelia Hart · A*" in labels and "James Fenn · A" in labels
    assert all("Local Only" not in lbl for lbl in labels)             # local number skipped
    phones = [int(e["phone"]) for e in entries]
    assert phones == sorted(phones)                                   # ascending, CallKit order


# ── client book (Share reverse flow) ─────────────────────────────────────────
def test_clients_requires_token(env):
    client, store, tok = env
    assert client.get("/v1/extension/clients").status_code == 401


def test_clients_returns_book_best_first_and_searches(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([
        _row(cid="c1", name="Bella Rossi", grade="B", phone="+44 7700 900001"),
        _row(cid="c2", name="Amelia Hart", grade="A*", phone="+44 7700 900002"),
        _row(cid="c3", name="", grade="A"),                            # nameless row skipped
    ])
    r = client.get("/v1/extension/clients", headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200
    body = r.json()
    names = [c["name"] for c in body["clients"]]
    assert names == ["Amelia Hart", "Bella Rossi"]                     # A* before B, nameless dropped
    assert body["clients"][0]["phone"] == "+44 7700 900002"           # a number to send to
    # name search
    r2 = client.get("/v1/extension/clients?q=bella", headers={"X-Halia-Ext-Token": ext})
    assert [c["name"] for c in r2.json()["clients"]] == ["Bella Rossi"]


# ── catalogue from storefront URLs (iOS save-while-browsing) ──────────────────
def test_handle_from_url_parsing():
    f = extension._handle_from_url
    assert f("https://shop.com/products/silk-scarf?variant=42") == "silk-scarf"
    assert f("https://shop.myshopify.com/en/products/Cashmere-Coat/") == "cashmere-coat"
    assert f("cashmere-coat") == "cashmere-coat"                      # bare handle
    assert f("https://shop.com/collections/new") == ""               # not a product url
    assert f("https://shop.com/") == "" and f("") == "" and f(None) == ""


def test_catalogue_from_urls_requires_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/catalogue_from_urls",
                       json={"urls": ["x"]}).status_code == 401


def test_catalogue_from_urls_needs_recognisable_urls(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    r = client.post("/v1/extension/catalogue_from_urls",
                    json={"urls": ["https://shop.com/about", "https://shop.com/collections/x"]},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 422


def test_catalogue_from_urls_builds_link(env, monkeypatch):
    client, store, tok = env
    ext = _ext_token(client, tok)
    monkeypatch.setattr(extension, "_ids_for_handles", lambda shop, handles: ["111", "222"])
    r = client.post("/v1/extension/catalogue_from_urls",
                    json={"urls": ["https://s.com/products/a", "https://s.com/products/b?variant=9"],
                          "name": "Amelia Hart"},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200
    j = r.json()
    assert j["resolved"] == 2 and j["requested"] == 2 and "/for?" in j["url"]


def test_products_from_urls_requires_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/products_from_urls",
                       json={"urls": ["x"]}).status_code == 401


def test_products_from_urls_empty_for_non_shopify(env):
    client, store, tok = env
    ext = _ext_token(client, tok)                       # env tenant is woocommerce (no Shopify token)
    r = client.post("/v1/extension/products_from_urls",
                    json={"urls": ["https://s.com/products/a"]},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200 and r.json()["products"] == []


def test_cart_link_from_urls_requires_token(env):
    client, store, tok = env
    assert client.post("/v1/extension/cart_link_from_urls",
                       json={"urls": ["x"]}).status_code == 401


def test_cart_link_from_urls_needs_recognisable_urls(env):
    client, store, tok = env
    ext = _ext_token(client, tok)
    r = client.post("/v1/extension/cart_link_from_urls",
                    json={"urls": ["https://shop.com/about"]},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 422


def test_cart_link_from_urls_builds_permalink(env, monkeypatch):
    client, store, tok = env
    ext = _ext_token(client, tok)
    monkeypatch.setattr(extension, "_products_for_handles", lambda shop, handles: [
        {"id": "1", "handle": "a", "variants": [{"id": "111"}]},
        {"id": "2", "handle": "b", "variants": [{"id": "222"}]},
    ])
    r = client.post("/v1/extension/cart_link_from_urls",
                    json={"urls": ["https://s.com/products/a", "https://s.com/products/b"]},
                    headers={"X-Halia-Ext-Token": ext})
    assert r.status_code == 200
    j = r.json()
    assert j["resolved"] == 2 and "/cart/111:1,222:1" in j["url"]


# ── Team seats (per-employee sign-in / sign-out) ─────────────────────────────
def test_seat_token_resolves_with_name(env):
    client, store, tok = env
    r = client.post("/v1/seats", json={"name": "Sarah"}, cookies={COOKIE: tok})
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "Sarah" and j["seat_id"] and "halia://connect?t=" in j["connect"]
    ctx = client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": j["token"]})
    assert ctx.status_code == 200 and ctx.json()["seat"] == "Sarah"


def test_seat_revoke_disables_its_token(env):
    client, store, tok = env
    seat = client.post("/v1/seats", json={"name": "Mo"}, cookies={COOKIE: tok}).json()
    hdr = {"X-Halia-Ext-Token": seat["token"]}
    assert client.get("/v1/extension/context", headers=hdr).status_code == 200
    assert client.post(f"/v1/seats/{seat['seat_id']}/revoke", cookies={COOKIE: tok}).status_code == 200
    assert client.get("/v1/extension/context", headers=hdr).status_code == 401


def test_legacy_shop_token_still_works_seatless(env):
    client, store, tok = env
    ext = _ext_token(client, tok)                         # the legacy shared per-shop token
    ctx = client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": ext})
    assert ctx.status_code == 200 and ctx.json()["seat"] is None


def test_seats_list_and_active_count(env):
    client, store, tok = env
    ana = client.post("/v1/seats", json={"name": "Ana"}, cookies={COOKIE: tok}).json()
    client.post("/v1/seats", json={"name": "Bea"}, cookies={COOKIE: tok})
    client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": ana["token"]})   # Ana signs in
    lst = client.get("/v1/seats", cookies={COOKIE: tok}).json()
    active = {s["name"]: s["active"] for s in lst["seats"]}
    assert {"Ana", "Bea"} <= set(active) and active["Ana"] is True and active["Bea"] is False
    assert lst["count"] == 1                              # only Ana active


def test_signout_makes_seat_inactive(env):
    client, store, tok = env
    ivy = client.post("/v1/seats", json={"name": "Ivy"}, cookies={COOKIE: tok}).json()
    client.get("/v1/extension/context", headers={"X-Halia-Ext-Token": ivy["token"]})
    assert client.get("/v1/seats", cookies={COOKIE: tok}).json()["count"] == 1
    assert client.post("/v1/extension/signout",
                       headers={"X-Halia-Ext-Token": ivy["token"]}).status_code == 200
    assert client.get("/v1/seats", cookies={COOKIE: tok}).json()["count"] == 0


# ── polish what the associate typed ─────────────────────────────────────────
def _polish(client, ext, body):
    return client.post("/v1/extension/polish", json=body, headers={"X-Halia-Ext-Token": ext})


def test_polish_requires_token_and_text(env):
    client, store, tok = env
    assert client.post("/v1/extension/polish", json={"text": "hi"}).status_code == 401
    ext = _ext_token(client, tok)
    assert _polish(client, ext, {"text": "  "}).status_code == 422


def test_polish_uses_ai_with_house_voice_and_language_rule(env, monkeypatch):
    from halia import llm
    seen = {}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda s, u, **k: seen.update(system=s, user=u) or "Dear Grace, the coat is back.")
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _polish(client, ext, {"text": "hi grace teh coat is back", "email": "grace@x.com",
                              "greeting": True, "signoff": True}).json()
    assert d["source"] == "ai" and d["text"] == "Dear Grace, the coat is back."
    assert "same language" in seen["system"] and "Text to polish:\nhi grace teh coat is back" in seen["user"]
    assert "greeting to the client by first name" in seen["user"]
    assert store.shop_metric(SHOP, "extension_polish_ai") == 1


def test_polish_rules_fallback_fixes_typos_and_applies_signoff(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(extension, "_seat_profile", lambda auth: {"name": "Sarah", "signoff": "Warmly, Sarah"})
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _polish(client, ext, {"text": "teh coat has arrvied  , i can hold it untill friday", "email": "grace@x.com",
                              "greeting": True, "signoff": True}).json()
    assert d["source"] == "rules"
    assert d["text"] == "Dear Grace,\n\nThe coat has arrived, I can hold it until friday\n\nWarmly, Sarah"


def test_polish_signoff_off_strips_the_closing(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    ext = _ext_token(client, tok)
    d = _polish(client, ext, {"text": "Hi there\nthe coat is here\n\nKind regards,\nSarah",
                              "greeting": False, "signoff": False}).json()
    assert d["text"] == "The coat is here"


def test_polish_respects_weekly_cap(env, monkeypatch):
    from halia import config, llm
    called = {"n": 0}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "complete", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "AI")
    monkeypatch.setattr(config, "LLM_WEEKLY_CAP", 1)
    client, store, tok = env
    ext = _ext_token(client, tok)
    assert _polish(client, ext, {"text": "hello"}).json()["source"] == "ai"
    assert _polish(client, ext, {"text": "hello"}).json()["source"] == "rules"
    assert called["n"] == 1


# ── the client's language ────────────────────────────────────────────────────
def test_brief_returns_the_clients_language_and_an_english_gloss(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: {**_AI_BRIEF, "reply": "Buongiorno Grace, il cappotto è tornato.",
                                                            "language": "it", "english": "Good morning Grace, the coat is back."})
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/brief", json={"email": "grace@x.com", "thread": [{"from": "them", "text": "Il cappotto è tornato?"}]},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["language"] == "it" and d["english"] == "Good morning Grace, the coat is back."


def test_brief_fallback_guesses_the_language(env, monkeypatch):
    from halia import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = client.post("/v1/extension/brief", json={"email": "grace@x.com",
                                                  "thread": [{"from": "them", "text": "Bonjour, je voudrais le manteau pour vendredi merci"}]},
                    headers={"X-Halia-Ext-Token": ext}).json()
    assert d["language"] == "fr" and d["english"] is None


def test_detect_language_heuristic():
    dl = extension._detect_language
    assert dl([{"from": "them", "text": "Hello, could you hold the coat for me please"}]) == "en"
    assert dl([{"from": "them", "text": "Grazie, vorrei il cappotto per sabato"}]) == "it"
    assert dl([{"from": "them", "text": "مرحبا، هل المعطف متوفر"}]) == "ar"
    assert dl([{"from": "them", "text": "请问外套有货吗"}]) == "zh"
    assert dl([]) == "en"


# ── remember this ────────────────────────────────────────────────────────────
class _FakeSink:
    def __init__(self, prefs=None):
        self.meta = {("c1", "preferences"): prefs} if prefs else {}
        self.tags = []

    def get_metafield(self, cid, key, namespace="halia"):
        return self.meta.get((cid, key))

    def set_metafield(self, cid, key, value, *a, **k):
        self.meta[(cid, key)] = value

    def tag_customer(self, cid, tags): self.tags.append(("+", tags))
    def untag_customer(self, cid, tags): self.tags.append(("-", tags))


def _remember(client, ext, body):
    return client.post("/v1/extension/remember", json=body, headers={"X-Halia-Ext-Token": ext})


def test_remember_ai_merges_into_the_clients_preferences(env, monkeypatch):
    import json
    from halia import llm
    from halia.api import board
    sink = _FakeSink(prefs=json.dumps({"sizes": "IT 40", "colours": ["navy"], "notes": ["buys for his wife"]}))
    monkeypatch.setattr(board, "_sink", lambda shop: sink)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: {
        "sizes": {"shoes": "IT 38"}, "colours": ["camel"], "materials": ["cashmere"],
        "occasions": [{"label": "daughter's wedding", "date": "2027-06-12"}], "notes": []})
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _remember(client, ext, {"email": "grace@x.com", "text": "I'm a 38 in shoes, love camel cashmere, my daughter's wedding is 12 June"}).json()
    assert d["source"] == "ai" and d["cid"] == "c1"
    assert d["summary"].startswith("IT 38, camel, cashmere, daughter's wedding June")
    assert d["occasion"] == {"label": "daughter's wedding", "date": "2027-06-12"}
    saved = json.loads(sink.meta[("c1", "preferences")])
    assert saved["sizes"] == {"size": "IT 40", "shoes": "IT 38"}
    assert saved["colours"] == ["navy", "camel"] and saved["materials"] == ["cashmere"]
    assert saved["occasions"] == [{"label": "daughter's wedding", "date": "2027-06-12"}]
    assert "buys for his wife" in saved["notes"]
    assert store.shop_metric(SHOP, "extension_remember_ai") == 1


def test_remember_rules_fallback_extracts_size_colour_and_month(env, monkeypatch):
    import json
    from halia import llm
    from halia.api import board
    sink = _FakeSink()
    monkeypatch.setattr(board, "_sink", lambda shop: sink)
    monkeypatch.setattr(llm, "available", lambda: False)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    d = _remember(client, ext, {"email": "grace@x.com", "text": "I wear IT 38, I love camel, and the wedding is in June"}).json()
    assert d["source"] == "rules"
    saved = json.loads(sink.meta[("c1", "preferences")])
    assert saved["sizes"] == {"size": "IT 38"} and saved["colours"] == ["camel"]
    assert saved["occasions"][0]["label"] == "wedding" and saved["occasions"][0]["date"].endswith("-06-01")
    assert d["occasion"]["date"].endswith("-06-01")


def test_remember_needs_text_and_an_identity(env, monkeypatch):
    client, store, tok = env
    ext = _ext_token(client, tok)
    assert _remember(client, ext, {"text": "IT 38"}).status_code == 422
    assert _remember(client, ext, {"email": "a@b.com"}).status_code == 422
    _seed([])
    monkeypatch.setattr(extension, "_lookup", lambda *a, **k: {"found": False})
    assert _remember(client, ext, {"email": "nobody@x.com", "text": "IT 38"}).json() == {"saved": False, "reason": "not_found"}


def test_remember_respects_weekly_cap(env, monkeypatch):
    from halia import config, llm
    from halia.api import board
    monkeypatch.setattr(board, "_sink", lambda shop: _FakeSink())
    called = {"n": 0}
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or
                        {"sizes": {}, "colours": [], "materials": [], "occasions": [], "notes": ["x"]})
    monkeypatch.setattr(config, "LLM_WEEKLY_CAP", 1)
    client, store, tok = env
    ext = _ext_token(client, tok)
    _seed([_row()])
    assert _remember(client, ext, {"email": "grace@x.com", "text": "hello"}).json()["source"] == "ai"
    assert _remember(client, ext, {"email": "grace@x.com", "text": "hello"}).json()["source"] == "rules"
    assert called["n"] == 1
