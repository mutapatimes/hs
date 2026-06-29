"""build_woo runner: slug + full WooCommerce->score->render through a fake transport."""
import build_woo
from build_woo import store_slug


def test_store_slug():
    assert store_slug("https://glennorah.co.uk") == "glennorah-co-uk"
    assert store_slug("http://Shop.Example.com/") == "shop-example-com"


def test_main_renders_dashboard(tmp_path, monkeypatch):
    orders = [
        {"id": 1, "customer_id": 5, "total": "1500.00", "discount_total": "0.00",
         "date_created_gmt": "2026-02-01T10:00:00",
         "billing": {"first_name": "Amara", "last_name": "Okafor",
                     "email": "amara@blackstone.com", "postcode": "W1K 1AA", "country": "GB"},
         "shipping": {}, "line_items": [{"quantity": 1}]},
    ]
    monkeypatch.setenv("WOO_STORE_URL", "https://glennorah.co.uk")
    monkeypatch.setenv("WOO_CONSUMER_KEY", "ck_test")
    monkeypatch.setenv("WOO_CONSUMER_SECRET", "cs_test")
    monkeypatch.setattr(build_woo, "http_transport", lambda: (lambda path, params: orders if params["page"] == 1 else []))
    monkeypatch.setattr(build_woo, "OUTPUT_DIR", tmp_path)

    build_woo.main()

    out = tmp_path / "glennorah-co-uk.html"
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "amara@blackstone.com" in html and "Work email" in html
