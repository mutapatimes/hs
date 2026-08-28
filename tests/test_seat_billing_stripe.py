"""Seat overage on Stripe-billed tenants: a seat line on the subscription kept at quantity =
seats beyond the bundle; the free scan allows one sign-in; the Team card knows the terms."""
import pytest
from fastapi.testclient import TestClient

from halia import config
from halia.api import billing, onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "maison-example"


class FakeStripe:
    def __init__(self, tier_price="price_signal", seat_item=None):
        self.calls, self.tier_price, self.seat_item = [], tier_price, seat_item

    def __call__(self, method, path, data=None):
        self.calls.append((method, path, data or {}))
        if method == "GET" and path.startswith("subscriptions/"):
            items = [{"id": "si_plan", "price": {"id": self.tier_price}, "quantity": 1}]
            if self.seat_item:
                items.append({"id": "si_seats", "price": {"id": "price_seat"}, "quantity": self.seat_item})
            return {"id": "sub_1", "status": "active", "items": {"data": items}}
        if path == "subscription_items":
            self.seat_item = int(data["quantity"])
        elif path == "subscription_items/si_seats":
            self.seat_item = None if method == "DELETE" else int(data["quantity"])
        return {"id": "si_seats"}

    def writes(self):
        return [(m, p, d) for m, p, d in self.calls if m != "GET"]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test")
    monkeypatch.setattr(config, "STRIPE_PRICE_ID", "price_signal")
    monkeypatch.setattr(config, "STRIPE_TIERS", "15000:price_discovery,75000:price_signal,*:price_atelier")
    monkeypatch.setattr(config, "STRIPE_SEAT_PRICE_ID", "price_seat")
    monkeypatch.setattr(config, "HALIA_FREE_SHOPS", "", raising=False)
    monkeypatch.setattr(billing, "_free_shops", lambda: set())
    tok = new_token()
    store.create_tenant(SHOP, "woocommerce", "Maison", hash_token(tok))
    fake = FakeStripe()
    monkeypatch.setattr(billing, "_stripe", fake)
    yield TestClient(app), store, tok, fake


def _seats(store, n):
    for i in range(n):
        sid = store.create_seat(SHOP, f"Associate {i}", hash_token(new_token()))
        store.touch_seat(sid)


def test_plan_key_read_from_the_tier_price(env):
    client, store, tok, fake = env
    assert billing.stripe_plan_key(SHOP) == "free"           # unpaid
    store.set_billing(SHOP, "active", "cus_1", "sub_1")
    assert billing.stripe_plan_key(SHOP) == "signal"


def test_seat_line_added_updated_and_removed(env):
    client, store, tok, fake = env
    store.set_billing(SHOP, "active", "cus_1", "sub_1")
    _seats(store, 7)                                          # Signal includes 5
    r = billing.sync_seat_quantity(SHOP)
    assert r["posted"] == 2 and fake.writes()[-1][1] == "subscription_items" and fake.writes()[-1][2]["quantity"] == 2
    assert billing.sync_seat_quantity(SHOP)["posted"] == 0   # idempotent
    _seats(store, 1)
    assert billing.sync_seat_quantity(SHOP)["posted"] == 1
    assert fake.writes()[-1][1] == "subscription_items/si_seats" and fake.writes()[-1][2]["quantity"] == 3
    for s in store.list_seats(SHOP)[:3]:
        store.revoke_seat(SHOP, s["id"])
    assert billing.sync_seat_quantity(SHOP)["posted"] == -3
    assert fake.writes()[-1][0] == "DELETE"


def test_sweep_covers_hosted_tenants_only_when_configured(env, monkeypatch):
    client, store, tok, fake = env
    store.set_billing(SHOP, "active", "cus_1", "sub_1")
    _seats(store, 6)
    assert billing.run_stripe_seat_billing() == {"checked": 1, "posted": 1, "errors": 0}
    monkeypatch.setattr(config, "STRIPE_SEAT_PRICE_ID", None)
    assert billing.run_stripe_seat_billing()["checked"] == 0


def test_free_scan_allows_one_sign_in_then_asks_for_a_plan(env):
    client, store, tok, fake = env
    r = client.post("/v1/seats", json={"name": "Owner"}, cookies={COOKIE: tok})
    assert r.status_code == 200
    r = client.post("/v1/seats", json={"name": "Sarah", "email": "sarah@maison.com"}, cookies={COOKIE: tok})
    assert r.status_code == 402 and "Choose a plan" in r.json()["detail"]
    terms = client.get("/v1/seats", cookies={COOKIE: tok}).json()["plan"]
    assert terms["free"] is True and terms["seats"] == 1
    store.set_billing(SHOP, "active", "cus_1", "sub_1")
    assert client.post("/v1/seats", json={"name": "Sarah", "email": "sarah@maison.com"}, cookies={COOKIE: tok}).status_code == 200
    terms = client.get("/v1/seats", cookies={COOKIE: tok}).json()["plan"]
    assert terms["metered"] and terms["included"] == 5 and terms["name"] == "Signal"
