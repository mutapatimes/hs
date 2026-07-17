"""The brand layer: host -> brand resolution, feature gating, and the host-aware front door."""
from starlette.testclient import TestClient

from halia.api.app import app
from halia import brands


def test_host_resolves_to_storeconcierge():
    assert brands.brand_for_host("storeconcierge.app").key == "storeconcierge"
    assert brands.brand_for_host("www.storeconcierge.app").key == "storeconcierge"
    assert brands.brand_for_host("STORECONCIERGE.APP:443").key == "storeconcierge"


def test_host_defaults_to_halia():
    assert brands.brand_for_host("haliascore.com").key == "halia"
    assert brands.brand_for_host("").key == "halia"
    assert brands.brand_for_host(None).key == "halia"


def test_feature_gating_excludes_the_engine_from_storeconcierge():
    sc = brands.STORECONCIERGE
    assert sc.enables("catalogues") and sc.enables("winback")
    assert not sc.enables("scoring") and not sc.enables("signals") and not sc.enables("map")
    assert brands.HALIA.enables("scoring")


def test_front_door_serves_storeconcierge_by_host():
    c = TestClient(app)
    r = c.get("/", headers={"host": "storeconcierge.app"})
    assert r.status_code == 200
    assert "Store Concierge" in r.text and "Look after your best customers" in r.text
    # the wealth product's language must never leak onto the Store Concierge front door
    assert "hidden VIC" not in r.text and "wealth" not in r.text.lower()


def test_front_door_defaults_to_halia():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "Your most valuable clients are already in your" in r.text
