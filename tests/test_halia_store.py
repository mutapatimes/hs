"""Secret store: encrypted token/Klaviyo roundtrip, deletion, and zero-PII schema."""
from cryptography.fernet import Fernet

from halia.store import ShopStore

SHOP = "acme.myshopify.com"


def test_token_and_klaviyo_roundtrip(tmp_path):
    s = ShopStore(db_path=tmp_path / "s.db")
    assert s.get_token(SHOP) is None and s.get_klaviyo(SHOP) is None
    s.save_shop(SHOP, "shpat_x")
    s.save_klaviyo(SHOP, "pk_abc")
    assert s.get_token(SHOP) == "shpat_x"
    assert s.get_klaviyo(SHOP) == "pk_abc"


def test_delete_shop_erases_everything(tmp_path):
    s = ShopStore(db_path=tmp_path / "s.db")
    s.save_shop(SHOP, "shpat_x")
    s.save_klaviyo(SHOP, "pk_y")
    s.delete_shop(SHOP)
    assert s.get_token(SHOP) is None and s.get_klaviyo(SHOP) is None


def test_secrets_are_encrypted_at_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("HALIA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    s = ShopStore(db_path=tmp_path / "e.db")
    s.save_shop(SHOP, "shpat_supersecret")
    raw = s._run("SELECT access_token FROM shops WHERE shop = :shop", {"shop": SHOP}, fetch="one")
    assert "shpat_supersecret" not in (raw["access_token"] or "")  # not plaintext on disk
    assert raw["access_token"].startswith("enc:v1:")
    assert s.get_token(SHOP) == "shpat_supersecret"                # decrypts on read


def test_schema_holds_no_customer_tables(tmp_path):
    """The only persisted tables are merchant secrets — never customer data."""
    s = ShopStore(db_path=tmp_path / "z.db")
    rows = s._run("SELECT name FROM sqlite_master WHERE type='table'", fetch="all")
    tables = {r["name"] for r in rows}
    assert "shops" in tables and "klaviyo" in tables
    assert {"scores", "orders", "dashboards"} & tables == set()  # purged / never created
