"""Free-scan gate: the whole book is scored and counted, but who anyone is stays masked until
the tenant is on a plan. The 30-day cap it replaces is gone."""
from build_mvp import mask_payload, render_payload


def _payload():
    return {
        "segments": {}, "data": [
            {"id": "C-0001", "cid": "1", "name": "Grace Ladoja", "init": "GL", "email": "g@x.com", "phone": "07700",
             "latent": 100, "spend": 50, "grade": "A*", "signals": [{"d": "Prime postcode: SW1"}],
             "orders": [{"id": 1}], "cart": {"value": 10}, "adminUrl": "https://admin/x", "city": "London"},
        ],
        "orders": [{"date": "2026-08-01", "name": "Grace Ladoja", "email": "g@x.com", "total": 120}],
        "stat_scored": "1", "stat_latent": "£100", "stat_count": "1",
        "stat_avgspend": "£50", "stat_toptier": "1", "full_history": True, "masked": False,
    }


def test_mask_withholds_identity_and_evidence_but_keeps_the_numbers():
    m = mask_payload(_payload())
    c = m["data"][0]
    assert c["name"] == "" and c["email"] == "" and c["phone"] == "" and c["init"] == ""
    assert c["signals"] == [] and c["orders"] == [] and c["cart"] is None and c["adminUrl"] == "" and c["cid"] == ""
    assert c["grade"] == "A*" and c["latent"] == 100 and c["city"] == "London"   # aggregates stay real
    o = m["orders"][0]
    assert o["name"] == "" and o["email"] == "" and o["total"] == 120
    assert m["masked"] is True and m["locked_count"] == 1 and m["locked_latent"] == "£100"
    assert m["stat_count"] == "1" and m["full_history"] is True


def test_render_injects_the_masked_flag():
    assert "const MASKED = false" in render_payload(_payload())
    assert "const MASKED = true" in render_payload(mask_payload(_payload()))


def test_render_injects_the_order_window():
    assert "const ORDER_WINDOW = 0" in render_payload(_payload())
    assert "const ORDER_WINDOW = 60" in render_payload({**_payload(), "order_window": 60})


def test_shopify_diagnosis_reads_scopes_orders_and_guests(monkeypatch):
    from halia.api import data
    from scoring import shopify_fetch
    monkeypatch.setattr(shopify_fetch, "http_transport", lambda shop, token: None)
    monkeypatch.setattr(shopify_fetch, "_run", lambda t, q, v, r: {
        "currentAppInstallation": {"accessScopes": [{"handle": "read_orders"}]},
        "customersCount": {"count": 12},
        "orders": {"nodes": [{"id": "1", "customer": None}, {"id": "2", "customer": None}, {"id": "3", "customer": {"id": "c"}}]}})
    d = data.shopify_diagnosis("s.myshopify.com", "tok")
    assert d == {"window": 60, "orders_recent": 3, "guest_orders": 2, "customers": 12}
    assert data.order_window_days("s.myshopify.com", "tok") == 60
    monkeypatch.setattr(shopify_fetch, "_run", lambda t, q, v, r: {"currentAppInstallation": {"accessScopes": [{"handle": "read_all_orders"}]}})
    assert data.order_window_days("s.myshopify.com", "tok") is None
    monkeypatch.setattr(shopify_fetch, "_run", lambda t, q, v, r: (_ for _ in ()).throw(RuntimeError("down")))
    assert data.shopify_diagnosis("s.myshopify.com", "tok")["window"] is None


def test_render_injects_the_diagnosis():
    assert 'const SYNC_DIAG = {}' in render_payload(_payload())
    assert '"guest_orders": 8' in render_payload({**_payload(), "sync_diag": {"orders_recent": 8, "guest_orders": 8}})
