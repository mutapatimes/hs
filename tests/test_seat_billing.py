"""Seat overage billed through Shopify: a capped usage line approved with the plan, then one
usage record per period (plus top-ups as the team grows). Nothing about customers involved."""
import pytest
from fastapi.testclient import TestClient

from halia import plans
from halia.api import billing_shopify as bs
from halia.api import onboarding, shopify_auth
from halia.api.app import app
from halia.api.tenant_auth import COOKIE, hash_token, new_token
from halia.store import ShopStore

SHOP = "seats.myshopify.com"


class FakeShopify:
    def __init__(self, plan_name="Discovery", period="2026-09-26T00:00:00Z", usage_line=True):
        self.calls, self.plan_name, self.period, self.usage_line = [], plan_name, period, usage_line

    def __call__(self, shop, query, variables):
        self.calls.append((query, variables))
        if "activeSubscriptions" in query:
            items = [{"id": "gid://li/rec", "plan": {"pricingDetails": {"__typename": "AppRecurringPricing"}}}]
            if self.usage_line:
                items.append({"id": "gid://li/use", "plan": {"pricingDetails": {"__typename": "AppUsagePricing"}}})
            return {"currentAppInstallation": {"activeSubscriptions": [
                {"id": "gid://sub/1", "name": self.plan_name, "status": "ACTIVE",
                 "currentPeriodEnd": self.period, "lineItems": items}]}}
        if "appUsageRecordCreate" in query:
            return {"appUsageRecordCreate": {"userErrors": [], "appUsageRecord": {"id": "gid://usage/%d" % len(self.calls)}}}
        return {}

    def usage_posts(self):
        return [v for q, v in self.calls if "appUsageRecordCreate" in q]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "s.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr(onboarding, "_start_sync", lambda *a, **k: None)
    tok = new_token()
    store.create_tenant(SHOP, "shopify", "Seats", hash_token(tok))
    store.set_billing(SHOP, "active", None, "gid://sub/1")
    monkeypatch.setattr(bs, "_token", lambda shop: "shptoken")
    fake = FakeShopify()
    monkeypatch.setattr(bs, "_gql", fake)
    yield store, fake, tok


def _seats(store, n):
    for i in range(n):
        sid = store.create_seat(SHOP, f"Associate {i}", hash_token(new_token()))
        store.touch_seat(sid)


def test_subscribe_carries_a_capped_usage_line():
    items = bs._line_items("discovery")
    assert items[0]["plan"]["appRecurringPricingDetails"]["price"]["amount"] == 150
    usage = items[1]["plan"]["appUsagePricingDetails"]
    assert usage["cappedAmount"]["amount"] == plans.SEAT_PRICE * plans.SEAT_CAP
    assert "3 seats" in usage["terms"] and "£15" in usage["terms"]
    assert len(bs._line_items("free")) == 1          # free scan has no seats to meter


def test_extra_seats_post_once_per_period_and_top_up(env):
    store, fake, _ = env
    _seats(store, 5)                                   # Discovery includes 3 → 2 extra
    r = bs.bill_seats(SHOP)
    assert r["posted"] == 2 and r["amount"] == 30
    post = fake.usage_posts()[-1]
    assert post["lineItemId"] == "gid://li/use" and post["price"]["amount"] == 30
    assert "2 additional associate seats" in post["description"]
    # same period, same team: nothing more is charged
    assert bs.bill_seats(SHOP)["posted"] == 0
    # a sixth seat mid-period: only the delta
    _seats(store, 1)
    r = bs.bill_seats(SHOP)
    assert r["posted"] == 1 and r["amount"] == 15
    # a new billing period: the full overage again
    fake.period = "2026-10-26T00:00:00Z"
    assert bs.bill_seats(SHOP)["posted"] == 3


def test_skips_when_not_metered_or_predating_seat_billing(env):
    store, fake, _ = env
    _seats(store, 5)
    fake.plan_name = "Maison"
    assert "not metered" in bs.bill_seats(SHOP)["skipped"]
    fake.plan_name, fake.usage_line = "Discovery", False
    assert "predates" in bs.bill_seats(SHOP)["skipped"]


def test_sweep_and_status(env):
    store, fake, tok = env
    _seats(store, 4)
    out = bs.run_seat_billing()
    assert out["checked"] == 1 and out["posted"] == 1 and out["errors"] == 0
    d = TestClient(app).get("/v1/plans/status", cookies={COOKIE: tok}).json()
    assert d["seatCap"] == plans.SEAT_CAP and d["seatBilling"]["charged"] == 1
    assert d["seatsInUse"] == 4 and d["extraSeats"] == 1
