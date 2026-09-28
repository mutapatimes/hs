"""The controls that keep real customer data out of the repository, the deploy and the logs."""
import logging
from pathlib import Path

import pytest

from halia import datavault, logredact
from halia.datavault import NotSyntheticSource, RealDataOutsideVault

ROOT = datavault.ROOT


def test_public_pages_can_only_be_built_from_synthetic_files():
    assert datavault.public_safe_source("sample_data/synthetic_100k.xlsx").name == "synthetic_100k.xlsx"
    for bad in ("sample_data/SAMPLE3.xlsx", "client.xlsx", "/tmp/export.csv"):
        with pytest.raises(NotSyntheticSource):
            datavault.public_safe_source(bad)


def test_a_real_export_inside_the_repo_is_refused_and_pointed_at_the_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("HALIA_REAL_DATA_DIR", str(tmp_path))
    stray = ROOT / "sample_data" / "stray_export_for_test.xlsx"
    stray.write_bytes(b"x")
    try:
        with pytest.raises(RealDataOutsideVault):
            datavault.resolve_data_path(stray)
        with pytest.raises(RealDataOutsideVault):
            datavault.real_source(stray)
        # the same name in the vault is found from either call
        (tmp_path / stray.name).write_bytes(b"x")
        assert datavault.resolve_data_path(stray) == tmp_path / stray.name
        assert datavault.real_source(stray.name) == tmp_path / stray.name
    finally:
        stray.unlink(missing_ok=True)


def test_no_real_export_lives_in_sample_data():
    for p in (ROOT / "sample_data").glob("*"):
        assert p.name == "README.md" or datavault.is_synthetic(p) or p.name.startswith("."), p.name


def test_scanner_recognises_the_tells_and_passes_synthetic():
    assert datavault.scan_text("hello amelia.hart42@gmail.com") == []
    assert datavault.scan_text("contact 1234567@qq.com") != []
    assert datavault.scan_text("mail 98765432@gmail.com") != []


def test_the_app_refuses_to_start_with_a_leak_in_the_public_tree(tmp_path, monkeypatch):
    leak = ROOT / "web" / "site" / "zz_leak_for_test.html"
    leak.write_text("<p>13579246@163.com</p>")
    try:
        with pytest.raises(RuntimeError):
            datavault.assert_public_tree_clean()
    finally:
        leak.unlink()
    datavault.assert_public_tree_clean()          # clean tree starts


def test_log_lines_never_carry_an_address_or_a_number():
    assert logredact.redact("sent to grace.lawson@example.com") == "sent to g***@example.com"
    assert "07700900123" not in logredact.redact("call +44 7700 900123 today")
    rec = logging.LogRecord("x", logging.INFO, "", 0, "user %s failed", ("a.person@shop.co.uk",), None)
    assert logredact.RedactFilter().filter(rec) and "a.person" not in rec.getMessage()


def test_the_schema_holds_no_customer_table(tmp_path):
    """Halia's database may hold merchants, staff and counters, never a customer record. A new
    table with customer-shaped columns fails here before it ships."""
    from halia.store import ShopStore
    st = ShopStore(db_path=tmp_path / "s.db")
    rows = st._run("SELECT name FROM sqlite_master WHERE type='table'", fetch="all")
    tables = {r["name"] for r in rows}
    allowed_person_tables = {"tenants", "seats", "staff_seats", "editors", "subscribers",
                             "email_journeys", "email_suppressions", "extension_tokens", "push_subs"}
    person_cols = {"email", "phone", "first_name", "last_name", "address", "address1", "postcode", "zip"}
    for t in tables:
        cols = {c["name"] for c in st._run(f"PRAGMA table_info({t})", fetch="all")}
        if cols & person_cols:
            assert t in allowed_person_tables, f"table {t} carries person columns {cols & person_cols}"
    assert not any(t in ("customers", "orders", "scores", "dashboards") for t in tables)
