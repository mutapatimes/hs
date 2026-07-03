"""build_bigcommerce runner: slug + full BigCommerce->score->render through a fake transport."""
import build_bigcommerce
from build_bigcommerce import store_slug


def test_store_slug():
    assert store_slug("abc12def") == "abc12def"
    assert store_slug("ABC_12/def") == "abc-12-def"


def test_main_renders_dashboard(tmp_path, monkeypatch):
    orders = [
        {"id": 1, "customer_id": 5, "email": "amara@blackstone.com", "status": "Shipped",
         "items_total": 1, "total_inc_tax": "1500.00", "date_created": "Sun, 01 Feb 2026 10:00:00 +0000",
         "billing_address": {"first_name": "Amara", "last_name": "Okafor",
                             "email": "amara@blackstone.com", "zip": "W1K 1AA", "country_iso2": "GB",
                             "street_1": "1 Mayfair", "city": "London"}},
    ]
    monkeypatch.setenv("BIGCOMMERCE_STORE_HASH", "abc12def")
    monkeypatch.setenv("BIGCOMMERCE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(build_bigcommerce, "http_transport",
                        lambda: (lambda path, params: orders if params["page"] == 1 else []))
    monkeypatch.setattr(build_bigcommerce, "OUTPUT_DIR", tmp_path)

    build_bigcommerce.main()

    out = tmp_path / "abc12def.html"
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "amara@blackstone.com" in html and "Work email" in html
