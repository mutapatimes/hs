"""halia/reference_bundle.py — encrypt local reference tables -> commit ciphertext -> restore on boot."""
import importlib

import pytest
from cryptography.fernet import Fernet


def _fresh_module(monkeypatch, tmp_root, key=None):
    if key is None:
        key = Fernet.generate_key().decode()
    monkeypatch.setenv("HALIA_ENCRYPTION_KEY", key)
    import halia.reference_bundle as rb
    importlib.reload(rb)
    monkeypatch.setattr(rb, "_ROOT", tmp_root)
    monkeypatch.setattr(rb, "BUNDLE_PATH", tmp_root / "reference_data" / "private_bundle.enc")
    return rb


def _seed_tables(root):
    for rel, text in [
        ("reference_data/companies/us_insiders.local.csv", "name,tier,company\nElon Musk,owner,SpaceX\n"),
        ("reference_data/charities/uk_charity_trustees.local.csv", "name\nJane Doe\n"),
    ]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_pack_then_unpack_restores_missing_tables(tmp_path, monkeypatch):
    rb = _fresh_module(monkeypatch, tmp_path)
    _seed_tables(tmp_path)
    packed, size = rb.write_bundle()
    assert size > 0 and "reference_data/companies/us_insiders.local.csv" in packed
    assert rb.BUNDLE_PATH.exists()

    # Simulate the deploy box: real .local tables absent, only the committed ciphertext present.
    (tmp_path / "reference_data/companies/us_insiders.local.csv").unlink()
    (tmp_path / "reference_data/charities/uk_charity_trustees.local.csv").unlink()

    written = rb.unpack()
    assert set(written) == set(packed)
    restored = (tmp_path / "reference_data/companies/us_insiders.local.csv").read_text()
    assert "Elon Musk,owner,SpaceX" in restored


def test_unpack_never_clobbers_an_existing_local_table(tmp_path, monkeypatch):
    rb = _fresh_module(monkeypatch, tmp_path)
    _seed_tables(tmp_path)
    rb.write_bundle()
    # A newer local edit must survive an unpack (dev copy wins).
    p = tmp_path / "reference_data/companies/us_insiders.local.csv"
    p.write_text("name,tier,company\nEdited Locally,owner,Acme\n", encoding="utf-8")
    written = rb.unpack()
    assert str(p).endswith("us_insiders.local.csv") and "us_insiders.local.csv" not in "\n".join(written)
    assert "Edited Locally" in p.read_text()          # untouched


def test_ciphertext_carries_no_plaintext_names(tmp_path, monkeypatch):
    rb = _fresh_module(monkeypatch, tmp_path)
    _seed_tables(tmp_path)
    rb.write_bundle()
    blob = rb.BUNDLE_PATH.read_bytes()
    assert b"Elon Musk" not in blob and b"Jane Doe" not in blob     # names never appear in the clear


def test_wrong_key_degrades_to_seeds_without_crashing(tmp_path, monkeypatch):
    rb = _fresh_module(monkeypatch, tmp_path)
    _seed_tables(tmp_path)
    rb.write_bundle()
    (tmp_path / "reference_data/companies/us_insiders.local.csv").unlink()
    # A box configured with the WRONG key must not crash — it falls back to seeds.
    monkeypatch.setenv("HALIA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    importlib.reload(rb)
    monkeypatch.setattr(rb, "_ROOT", tmp_path)
    monkeypatch.setattr(rb, "BUNDLE_PATH", tmp_path / "reference_data" / "private_bundle.enc")
    assert rb.unpack() == []
    assert not (tmp_path / "reference_data/companies/us_insiders.local.csv").exists()


def test_pack_requires_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("HALIA_ENCRYPTION_KEY", raising=False)
    import halia.reference_bundle as rb
    importlib.reload(rb)
    monkeypatch.setattr(rb, "_ROOT", tmp_path)
    with pytest.raises(RuntimeError):
        rb.pack()
