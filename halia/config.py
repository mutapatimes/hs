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

# Halia's own Brevo contact lists (NOT the merchant's audience — those are the CRM sinks).
# Demo leads and new clients are auto-added to these so Brevo automations (demo nurture,
# client welcome series) fire. IDs from Brevo → Contacts → Lists. Defaults match the
# Demo (#3) / Clients (#4) lists. Sync is best-effort and no-ops when the API key is unset.
BREVO_LIST_DEMO = os.environ.get("HALIA_BREVO_LIST_DEMO", "3")
BREVO_LIST_CLIENTS = os.environ.get("HALIA_BREVO_LIST_CLIENTS", "4")

# Shared secret for the lifecycle-email scheduler. A Render Cron Job POSTs /internal/cron/run
# with this in the X-Cron-Key header to fire due journey emails. Unset -> the endpoint is disabled.
CRON_KEY = os.environ.get("HALIA_CRON_KEY") or None

# Self-service onboarding gate. When set, the /connect page requires this code so the
# public can't create tenants; share it with a client to let them self-onboard. Unset
# (None) = open onboarding (fine for local dev).
SIGNUP_CODE = os.environ.get("HALIA_SIGNUP_CODE") or None

# Mini-CMS admin key. When set, /admin lets the operator edit marketing copy (<!--cms:key-->
# blocks) without touching code. Unset -> /admin is disabled.
ADMIN_KEY = os.environ.get("HALIA_ADMIN_KEY") or None

# Console dashboard key. When set, /console gives you a cross-tenant birds-eye view
# (client counts, weekly activity, billing, live status). Kept separate from ADMIN_KEY because
# this surface exposes business metrics across every tenant. Unset -> /console is disabled.
CONSOLE_KEY = os.environ.get("HALIA_CONSOLE_KEY") or None

# Stripe billing. When STRIPE_SECRET_KEY and STRIPE_PRICE_ID are both set, the hosted
# dashboard is gated: a newly connected tenant sees a teaser (their hidden-VIC count and
# latent value) until they subscribe via Stripe Checkout. Unset = billing off, the dashboard
# is fully open (preserves current behaviour and never locks out an existing client).
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY") or None
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID") or None
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET") or None
# Optional preconfigured Stripe coupon id for the 50%-off retention offer (else created ad-hoc).
STRIPE_RETENTION_COUPON = os.environ.get("STRIPE_RETENTION_COUPON") or None
# Tenant keys granted full access without paying (e.g. a comped first client), comma-separated.
HALIA_FREE_SHOPS = {s.strip() for s in os.environ.get("HALIA_FREE_SHOPS", "").split(",") if s.strip()}

# Origin-proxy signals (nationality / name / ethnicity tells) are OFF by default for every
# tenant. List here, comma-separated, only the shop keys whose merchant has DOCUMENTED a
# lawful basis to use them; those tenants then score with include_origin=True. Default empty
# = off everywhere (lawful-by-default). Operator-controlled, not a self-serve merchant toggle.
HALIA_ORIGIN_SIGNAL_SHOPS = {s.strip() for s in
                             os.environ.get("HALIA_ORIGIN_SIGNAL_SHOPS", "").split(",") if s.strip()}

# Shopify one-click onboarding via your app's install link (Dev Dashboard -> Distribution ->
# Manage custom install link). When set, the wizard's 'Connect with Shopify' button opens this
# link; the merchant installs, the embedded app stores their token, and onboarding picks it up.
# Unset = the wizard offers only the manual Admin API token method for Shopify.
HALIA_SHOPIFY_INSTALL_URL = os.environ.get("HALIA_SHOPIFY_INSTALL_URL") or ""

# Cap the WooCommerce pull for the interactive dashboard (recent orders are the most
# actionable; a full back-catalogue pull on a big store can take many minutes). Defaults to
# 60 pages (~6,000 most-recent orders) so the first scoring is fast; set HALIA_WOO_MAX_PAGES=0
# for the full history, or another number to taste. Pages are 100 orders each.
WOO_MAX_PAGES = int(os.environ.get("HALIA_WOO_MAX_PAGES", "60")) or None

# Same cap for BigCommerce. Pages are 250 orders each (BC v2 max), so 60 pages is ~15,000
# most-recent orders; set HALIA_BIGCOMMERCE_MAX_PAGES=0 for the full history.
BIGCOMMERCE_MAX_PAGES = int(os.environ.get("HALIA_BIGCOMMERCE_MAX_PAGES", "60")) or None

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
