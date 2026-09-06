"""Halia for Japan: the first localisation layer, and the pages that use it.

The design rule under test: a store whose house voice is Japanese shows its clients Japanese, a
store that never chose stays exactly as before, and a missing translation falls back to English
rather than to a blank. Plus the two Japan bugs this work surfaced: yen with decimals, and
kanji-heavy Japanese read as Chinese.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from halia import i18n
from halia.api import board, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "maison.myshopify.com"


def test_every_language_carries_every_key_with_the_same_tokens():
    # A key missing from ja silently falls back to English, which is fine once, and a slow rot if
    # nothing checks. Mismatched {tokens} would raise at render time in front of a client.
    en = i18n.STRINGS["en"]
    for lang, table in i18n.STRINGS.items():
        assert set(table) == set(en), f"{lang} keys differ from en"
        for key, text in table.items():
            assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", en[key])), \
                f"{lang}:{key} tokens differ"


def test_fallbacks_never_blank_a_page():
    assert i18n.t("de", "cat.pick") == "Pick"          # untranslated language reads English
    assert i18n.t("ja", "no.such.key") == "no.such.key"
    assert i18n.clean_lang("JA ") == "ja" and i18n.clean_lang("fr") == "en"


def test_japanese_dates_read_japanese():
    d = datetime(2026, 9, 12, 15, 0)                    # a Saturday
    assert i18n.when_words(d, "ja") == "9月12日（土）15:00"
    assert i18n.when_words(d, "en") == "Saturday 12 September at 15:00"


class FakeSink:
    def __init__(self): self.meta, self.tags = {}, []
    def get_metafield(self, cid, key, namespace="halia"): return self.meta.get((cid, key))
    def set_metafield(self, cid, key, value, *a, **k): self.meta[(cid, key)] = value
    def tag_customer(self, cid, tags): self.tags.append(("+", cid, tags))
    def untag_customer(self, cid, tags): self.tags.append(("-", cid, tags))
    def pipeline_cards(self):
        out = {}
        for (cid, key), raw in self.meta.items():
            if key == "pipeline":
                p = json.loads(raw)
                out[cid] = {"cid": cid, "stage": p.get("stage"), "name": "Grace", "email": "g@x.com",
                            "assignee": p.get("assignee"), "activity": p.get("activity") or [],
                            "appointments": p.get("appointments") or []}
        return out


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "j.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "銀座メゾン", hash_token(tok))
    sink = FakeSink()
    monkeypatch.setattr(board, "_sink", lambda shop: sink)
    yield TestClient(app, cookies={COOKIE: tok}), store


def _speak_ja(store):
    store.save_settings(SHOP, json.dumps({"voice": {"language": "ja"}}))


def test_the_invite_speaks_the_stores_language(env):
    client, store = env
    _speak_ja(store)
    when = (datetime.now(timezone.utc) + timedelta(days=4)).replace(hour=15, minute=0,
                                                                    second=0, microsecond=0)
    d = client.post("/v1/board/appointment",
                    json={"cid": "c1", "when": when.isoformat(), "place": "銀座本店",
                          "client_name": "優子"}).json()
    msg = d["links"]["message"]
    assert "ご予約を承りました" in msg and "銀座本店" in msg and f"{when.month}月{when.day}日" in msg
    token = d["links"]["invite"].rsplit("/i/", 1)[1]
    page = client.get(f"/i/{token}").text
    assert 'lang="ja"' in page and "カレンダーに追加" in page and "Googleカレンダー" in page
    assert "Hiragino" in page and "Add to my calendar" not in page


def test_a_store_that_never_chose_reads_exactly_as_before(env):
    client, store = env
    when = (datetime.now(timezone.utc) + timedelta(days=4)).replace(hour=11, minute=0,
                                                                    second=0, microsecond=0)
    d = client.post("/v1/board/appointment",
                    json={"cid": "c1", "when": when.isoformat(), "place": "Mount Street"}).json()
    assert d["links"]["message"].startswith("Your appointment is set for ")
    page = client.get("/i/" + d["links"]["invite"].rsplit("/i/", 1)[1]).text
    assert 'lang="en"' in page and "Add to my calendar" in page and "Hiragino" not in page


def test_the_capture_form_speaks_japanese_with_japanese_structure(env, monkeypatch):
    from halia.api.capture import _qr_page
    monkeypatch.setattr("halia.i18n.client_lang", lambda shop: "ja" if shop == SHOP else "en")
    page = _qr_page("銀座メゾン", SHOP)
    assert 'lang="ja"' in page and "お客様情報" in page.replace("\n", "")[:4000] or "ご登録" in page
    # family name first, then given name, then the reading — the order every Japanese form uses
    assert page.index('name="last_name"') < page.index('name="first_name"') < page.index('name="furigana"')
    # and the address postcode-first
    assert page.index('name="postcode"') < page.index('name="address"')
    assert "登録する" in page

    en = __import__("halia.api.capture", fromlist=["_qr_page"])._qr_page("Maison", "other.myshopify.com")
    # the English form is untouched: given name first, no reading field, address-first
    assert en.index('name="first_name"') < en.index('name="last_name"')
    assert 'name="furigana"' not in en
    assert en.index('name="address"') < en.index('name="postcode"')


def test_the_reading_lands_with_their_preferences(env, monkeypatch):
    from halia.api import capture as cap
    seen = {}
    monkeypatch.setattr(cap, "_find_existing", lambda *a, **k: None)
    monkeypatch.setattr(cap, "get_valid_token", lambda shop: None)   # woo path is simpler to stub
    monkeypatch.setattr(cap, "_perform_capture_woo",
                        lambda shop, body, *a, **k: seen.update(body) or {"ok": True})
    monkeypatch.setattr("halia.api.shopify_auth.shop_store", lambda: env[1])
    env[1].create_tenant(SHOP, "woocommerce", "Maison", "h")
    cap.perform_capture(SHOP, {"first_name": "優子", "last_name": "田中",
                               "furigana": "タナカ ユウコ", "email": "y@x.jp",
                               "preferences": "size 36"}, "qr")
    assert seen["preferences"] == "フリガナ: タナカ ユウコ · size 36"


def test_yen_never_shows_decimals():
    from halia.api.catalog import _price_str
    from halia.catalog_form import _price
    assert _price({"price": "250000", "currency": "JPY"}) == "¥250,000"
    assert _price_str({"price": "250000", "currency": "JPY"}) == "¥250,000"
    assert _price({"price": "1200", "currency": "GBP"}) == "£1,200.00"   # sterling untouched


def test_kanji_heavy_japanese_is_not_chinese():
    from halia.api.extension import _detect_language
    assert _detect_language([{"from": "them", "text": "商品の在庫を確認したいです。"}]) == "ja"
    assert _detect_language([{"from": "them", "text": "你好，请问这个还有货吗"}]) == "zh"


def test_the_ja_strings_carry_no_machine_tone_markers():
    # A light guard: the drafted keigo must not slip into plain form on the client-facing verbs.
    for key in ("cat.thanks", "cap.lead", "cap.good_hands", "appt.message"):
        text = i18n.STRINGS["ja"][key]
        assert any(polite in text for polite in ("ます", "ました", "ください", "ございます")), key
