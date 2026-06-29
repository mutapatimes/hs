"""Encrypt secrets at rest (the only things Halia persists: merchant API tokens/keys).

Halia stores **no customer data**. The few merchant secrets it must keep to function — the
Shopify offline access token and the Klaviyo API key — are encrypted here with Fernet
(AES-128-CBC + HMAC), keyed by the `HALIA_ENCRYPTION_KEY` env var. So even a full database
dump never exposes a usable token.

In local dev with no key set, values are stored in plaintext (SQLite, never production) and
a one-time warning is logged — production MUST set `HALIA_ENCRYPTION_KEY`.

Generate a key once:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import os
import sys

_PREFIX = "enc:v1:"  # marks an encrypted value so we can decrypt only what we encrypted
_warned = False


def _fernet():
    key = os.environ.get("HALIA_ENCRYPTION_KEY")
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


def _warn_plaintext() -> None:
    global _warned
    if not _warned:
        _warned = True
        print("WARNING: HALIA_ENCRYPTION_KEY not set — secrets stored UNENCRYPTED "
              "(local dev only; set it in production).", file=sys.stderr)


def encrypt(value: str | None) -> str | None:
    """Encrypt a secret for storage. No-op (with a warning) if no key is configured."""
    if value is None:
        return None
    f = _fernet()
    if f is None:
        _warn_plaintext()
        return value
    return _PREFIX + f.encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """Decrypt a stored secret. Plaintext (un-prefixed) values pass through unchanged."""
    if value is None or not value.startswith(_PREFIX):
        return value
    f = _fernet()
    if f is None:  # encrypted data but no key — can't recover
        return None
    return f.decrypt(value[len(_PREFIX):].encode()).decode()
