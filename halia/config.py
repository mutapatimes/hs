"""Environment-based configuration for the Halia application layer.

Filesystem paths for the brain live in the top-level `config.py`; this module holds
the *application* settings (where scores are stored, the VIC threshold, which surfaces
are switched on, and platform credentials). Everything is read from the environment so
the same code runs locally, in a container, or in a cron job. A `.env` file is loaded
if present (and git-ignored).
"""
from __future__ import annotations

import os
from pathlib import Path

from config import ROOT  # reuse the project root

# Best-effort .env loading without adding a dependency.
def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# Where the SQLite score store lives (git-ignored *.db). Override with HALIA_DB_PATH.
DB_PATH = Path(os.environ.get("HALIA_DB_PATH", str(ROOT / "output" / "halia.db")))

# Multi-tenant Postgres (Render sets this). When present the store uses Postgres
# instead of SQLite. Render's DATABASE_URL uses the postgres:// scheme.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# The embedded Shopify app's own credentials (from the HALIA Dev Dashboard app) —
# distinct from a single store's Admin token; used to verify session tokens and to
# token-exchange per installed shop.
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
HALIA_APP_URL = os.environ.get("HALIA_APP_URL", "").rstrip("/")

# Merchant's VIC spend cutoff (the hidden-vs-known gate). Falls back to the engine default.
VIC_THRESHOLD = float(os.environ.get("HALIA_VIC_THRESHOLD", "5000"))

# Shopify (reuse the existing env vars the fetch layer already reads).
SHOPIFY_SHOP = os.environ.get("SHOPIFY_SHOP")
SHOPIFY_ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")

# Which write-back sinks are lit. Shopify is the first surface; the rest stay dark
# (stubs) until a real customer turns them on.
ENABLE_SHOPIFY_SINK = _flag("HALIA_ENABLE_SHOPIFY_SINK", False)
ENABLE_KLAVIYO_SINK = _flag("HALIA_ENABLE_KLAVIYO_SINK", False)
ENABLE_HUBSPOT_SINK = _flag("HALIA_ENABLE_HUBSPOT_SINK", False)

KLAVIYO_API_KEY = os.environ.get("KLAVIYO_API_KEY")
HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN")
