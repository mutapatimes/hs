"""The hosted dashboard serves the Store Concierge desk for storeconcierge-brand tenants."""
import json

import pytest
from fastapi.testclient import TestClient

from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "t.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_validate_woo", lambda *a, **k: (True, ""))  # no network
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    monkeypatch.setattr("halia.config.SIGNUP_CODE", None)
    return TestClient(app), store


def _tenant(store, shop):
    tok = new_token()
    store.create_tenant(shop, "shopify", "Maison Aurelle", hash_token(tok))
    return tok


def test_brand_defaults_to_halia_and_is_settable(client):
    from halia.storeconcierge.tenant import brand_of, is_storeconcierge, set_brand
    _, store = client
    _tenant(store, "shopx")
    assert brand_of("shopx") == "halia" and not is_storeconcierge("shopx")
    set_brand("shopx", "storeconcierge")
    assert brand_of("shopx") == "storeconcierge" and is_storeconcierge("shopx")


def test_storeconcierge_tenant_gets_the_desk_not_the_wealth_dashboard(client):
    from halia.cache import cache
    from halia.storeconcierge.tenant import set_brand
    c, store = client
    tok = _tenant(store, "scshop")
    set_brand("scshop", "storeconcierge")
    desk = {"stats": {"customers": 2, "active": 1, "lapsed": 1, "winback": 1, "orders": 1, "ltv": 100.0},
            "customers": [{"cid": "1", "name": "Ava Reed", "email": "a@x.com", "phone": "",
                           "orders": 2, "spent": 80, "last": "2026-07-10", "days": 7, "status": "active"}],
            "winback": [], "orders": []}
    cache.set("scshop", [], {"desk": desk}, {})
    try:
        c.cookies.set(COOKIE, tok)
        r = c.get("/app")
        assert r.status_code == 200
        assert "Your desk" in r.text and "Store Concierge" in r.text and "Ava Reed" in r.text
        # the wealth product must never leak into the Store Concierge desk
        assert "hidden VIC" not in r.text and "wealth" not in r.text.lower()
    finally:
        cache.evict("scshop")


def test_onboard_marks_the_storeconcierge_brand(client):
    """A signup declaring the storeconcierge brand is stored as such (the SC connect flow)."""
    import json as _json
    from halia.storeconcierge.tenant import brand_of
    c, store = client
    r = c.post("/v1/onboard", json={
        "store_url": "https://maison-aurelle.com", "consumer_key": "ck", "consumer_secret": "cs",
        "label": "Maison Aurelle", "accept_terms": True, "platform": "", "brand": "storeconcierge"})
    assert r.status_code == 200
    s = _json.loads(store.get_settings_raw("maison-aurelle-com"))
    assert s["brand"] == "storeconcierge"
    assert brand_of("maison-aurelle-com") == "storeconcierge"


def test_onboard_defaults_to_halia_brand(client):
    import json as _json
    c, store = client
    c.post("/v1/onboard", json={"store_url": "https://plain.co.uk", "consumer_key": "ck",
                                "consumer_secret": "cs", "label": "Plain", "accept_terms": True,
                                "platform": ""})
    s = _json.loads(store.get_settings_raw("plain-co-uk"))
    assert s["brand"] == "halia"


def test_clienteling_runs_on_a_scored_style_frame():
    """_finalize attaches payload['desk'] = clienteling_payload(scored); prove that call works on
    the post-scoring frame shape (Name/EMAIL_ADDR/Spent/Last Shopped/Count of CUST_ID/PHONE)."""
    import pandas as pd
    from halia.storeconcierge.clienteling import clienteling_payload
    scored = pd.DataFrame([
        {"CUST_ID": 1, "Name": "Ava", "EMAIL_ADDR": "a@x.com", "Count of CUST_ID": 2,
         "Spent": 500, "Last Shopped": "2026-07-10", "PHONE": "07700900123",
         "score": 88, "grade": "A"},   # score columns present, and ignored
    ])
    p = clienteling_payload(scored, as_of=pd.Timestamp("2026-07-17"))
    assert p["stats"]["customers"] == 1
    assert p["customers"][0]["name"] == "Ava" and "score" not in p["customers"][0]
