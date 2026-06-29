"""Secret encryption at rest (Fernet)."""
from cryptography.fernet import Fernet

from halia import crypto


def test_encrypt_roundtrip_with_key(monkeypatch):
    monkeypatch.setenv("HALIA_ENCRYPTION_KEY", Fernet.generate_key().decode())
    enc = crypto.encrypt("a-secret-token")
    assert enc.startswith("enc:v1:") and "a-secret-token" not in enc
    assert crypto.decrypt(enc) == "a-secret-token"


def test_plaintext_fallback_without_key(monkeypatch):
    monkeypatch.delenv("HALIA_ENCRYPTION_KEY", raising=False)
    assert crypto.encrypt("x") == "x"   # local-dev fallback (with a logged warning)
    assert crypto.decrypt("x") == "x"


def test_none_passthrough():
    assert crypto.encrypt(None) is None and crypto.decrypt(None) is None
