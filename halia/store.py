"""Secret store — the ONLY thing Halia persists. No customer data, ever.

Halia is zero-retention for customer PII: customers are fetched from Shopify, scored in
memory, shown / written back, and never written to disk or database (see `halia.cache`).
The only durable state is the handful of **merchant secrets** needed to call their APIs —
the Shopify offline access token and the Klaviyo key — and both are **encrypted at rest**
(`halia.crypto`).

Two backends behind one interface: Postgres when `DATABASE_URL` is set (production), else a
local SQLite file (dev/tests). On startup any legacy PII tables from earlier versions are
**dropped**, so a deploy purges previously-stored customer data.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from halia import crypto
from halia.config import DATABASE_URL, DB_PATH

_TABLES = [
    """CREATE TABLE IF NOT EXISTS shops (
        shop         TEXT PRIMARY KEY,
        access_token TEXT,
        installed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS klaviyo (
        shop         TEXT PRIMARY KEY,
        api_key      TEXT,
        connected_at TEXT
    )""",
    # Merchant configuration (VIC threshold, email templates, sign-off) — NOT customer
    # data and NOT secret, so stored as plain JSON.
    """CREATE TABLE IF NOT EXISTS settings (
        shop TEXT PRIMARY KEY,
        data TEXT
    )""",
    # Self-service tenants (non-Shopify, e.g. WooCommerce). `kind` is the data source;
    # `token_hash` is the sha256 of the private dashboard-link token (never the token
    # itself). One row per onboarded client, keyed by the same `shop` tenant key.
    """CREATE TABLE IF NOT EXISTS tenants (
        shop       TEXT PRIMARY KEY,
        kind       TEXT,
        label      TEXT,
        token_hash TEXT,
        created_at TEXT
    )""",
    # WooCommerce REST credentials (read-only ck_/cs_), encrypted at rest.
    """CREATE TABLE IF NOT EXISTS woocommerce (
        shop            TEXT PRIMARY KEY,
        store_url       TEXT,
        consumer_key    TEXT,
        consumer_secret TEXT,
        connected_at    TEXT
    )""",
    # BigCommerce API-account credentials (store hash + read-only access token), encrypted.
    """CREATE TABLE IF NOT EXISTS bigcommerce (
        shop         TEXT PRIMARY KEY,
        store_hash   TEXT,
        access_token TEXT,
        connected_at TEXT
    )""",
    # Centra Integration-API credentials (instance base URL + Order:read token), encrypted.
    """CREATE TABLE IF NOT EXISTS centra (
        shop         TEXT PRIMARY KEY,
        base_url     TEXT,
        api_token    TEXT,
        connected_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS scayle (
        shop         TEXT PRIMARY KEY,
        base_url     TEXT,
        access_token TEXT,
        connected_at TEXT
    )""",
    # Marketing-site newsletter signups (just an email + when). Not customer data.
    """CREATE TABLE IF NOT EXISTS subscribers (
        email        TEXT PRIMARY KEY,
        subscribed_at TEXT
    )""",
    # Per-shop order-alert webhook token (capability for the alerts webhook). Not customer data.
    """CREATE TABLE IF NOT EXISTS webhooks (
        shop       TEXT PRIMARY KEY,
        token      TEXT,
        created_at TEXT
    )""",
    # Per-shop browser-extension token (the sha256 hash only, like tenants.token_hash). The
    # capability the Halia badge extension presents to the single-customer lookup endpoint.
    """CREATE TABLE IF NOT EXISTS extension_tokens (
        shop       TEXT PRIMARY KEY,
        token_hash TEXT,
        created_at TEXT
    )""",
    # Web Push subscriptions (browser endpoints + keys). Not customer data.
    """CREATE TABLE IF NOT EXISTS push_subs (
        endpoint TEXT PRIMARY KEY,
        shop     TEXT,
        p256dh   TEXT,
        auth     TEXT,
        created_at TEXT
    )""",
    # Per-shop Mailchimp connection: encrypted API key (...-dc) + the chosen audience.
    """CREATE TABLE IF NOT EXISTS mailchimp (
        shop         TEXT PRIMARY KEY,
        api_key      TEXT,
        list_id      TEXT,
        list_name    TEXT,
        connected_at TEXT
    )""",
    # Per-shop HubSpot connection: encrypted Private App token + the portal id (for deep links).
    """CREATE TABLE IF NOT EXISTS hubspot (
        shop         TEXT PRIMARY KEY,
        api_token    TEXT,
        portal_id    TEXT,
        connected_at TEXT
    )""",
    # Per-shop Endear (retail clienteling CRM) connection: encrypted per-brand API key.
    """CREATE TABLE IF NOT EXISTS endear (
        shop         TEXT PRIMARY KEY,
        api_key      TEXT,
        connected_at TEXT
    )""",
    # Per-shop Slack alerts: an encrypted Incoming Webhook URL (contains a secret token).
    """CREATE TABLE IF NOT EXISTS slack (
        shop         TEXT PRIMARY KEY,
        webhook_url  TEXT,
        channel      TEXT,
        connected_at TEXT
    )""",
    # Site-wide editable content (the mini CMS): overrides for <!--cms:key--> blocks in the
    # marketing pages. Not per-shop, not customer data — just website copy.
    """CREATE TABLE IF NOT EXISTS content (
        key        TEXT PRIMARY KEY,
        value      TEXT,
        updated_at TEXT
    )""",
    # Per-shop subscription state (Stripe). Not customer data. status: active / trialing /
    # canceled / comped. customer_id + subscription_id are Stripe references, not secrets.
    """CREATE TABLE IF NOT EXISTS billing (
        shop            TEXT PRIMARY KEY,
        status          TEXT,
        customer_id     TEXT,
        subscription_id TEXT,
        updated_at      TEXT
    )""",
    # Associate-feedback tally, AGGREGATE ONLY — how often each signal appeared on a customer
    # the merchant marked a "good call" vs "not a fit". No customer identifier is stored (the
    # per-customer verdict lives merchant-side as a Shopify tag), so this keeps zero-retention
    # while giving outcome labels to calibrate signal weights on later.
    """CREATE TABLE IF NOT EXISTS feedback_stats (
        shop   TEXT,
        signal TEXT,
        fit    INTEGER DEFAULT 0,
        nofit  INTEGER DEFAULT 0,
        PRIMARY KEY (shop, signal)
    )""",
    # Activity counters for the console dashboard, AGGREGATE ONLY. A row is a per-shop, per-ISO-week
    # tally of an activity metric (scans run, customers scanned, hidden VICs surfaced, emails sent,
    # actions pushed to a sink). No customer identifier is ever stored — a shop domain, a week
    # bucket, a metric name and an integer are not customer data, so this keeps zero-retention while
    # giving you a birds-eye view of what is happening across tenants over time.
    """CREATE TABLE IF NOT EXISTS metrics (
        shop   TEXT,
        week   TEXT,
        metric TEXT,
        count  INTEGER DEFAULT 0,
        PRIMARY KEY (shop, week, metric)
    )""",
    # Halia's own lifecycle email journeys (demo nurture, client welcome, recurring weekly nudge).
    # These hold Halia's OWN business contacts (leads/clients), not merchant customers — same
    # footing as `subscribers`. `journey` in {demo, client, weekly}; `step` is the next index to
    # send; `next_at` is when it's due; `data` is a small JSON blob (first name, shop).
    """CREATE TABLE IF NOT EXISTS email_journeys (
        email      TEXT,
        journey    TEXT,
        step       INTEGER DEFAULT 0,
        next_at    TEXT,
        data       TEXT,
        done       INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT,
        PRIMARY KEY (email, journey)
    )""",
    # One-click unsubscribe suppression. Checked before every lifecycle send.
    """CREATE TABLE IF NOT EXISTS email_suppressions (
        email      TEXT PRIMARY KEY,
        reason     TEXT,
        created_at TEXT
    )""",
    # Blog posts (the native CMS). Company content, not customer data — same trust class as
    # `content`. body_html is operator-authored (WYSIWYG), <script>/<iframe> stripped on save.
    """CREATE TABLE IF NOT EXISTS blog_posts (
        slug           TEXT PRIMARY KEY,
        title          TEXT,
        dek            TEXT,
        body_html      TEXT,
        author         TEXT,
        cover_image_id TEXT,
        tags           TEXT,
        status         TEXT DEFAULT 'draft',
        published_at   TEXT,
        created_at     TEXT,
        updated_at     TEXT
    )""",
    # Blog images, stored in the DB so they survive Render's ephemeral filesystem. Served at
    # /blog/img/<id>. `data_b64` is base64 TEXT (identical DDL on SQLite and Postgres; no BLOB/BYTEA
    # divergence) — blog images are few and small, so the ~33% overhead is immaterial.
    """CREATE TABLE IF NOT EXISTS blog_images (
        id         TEXT PRIMARY KEY,
        mime       TEXT,
        data_b64   TEXT,
        created_at TEXT
    )""",
    # Product catalogs (the catalog-PDF builder). Company/product content, not customer PII.
    # `config_json` holds the selection (product ids or collection/tag/vendor filters) + template +
    # brand colour; `pdf_b64` is the last generated PDF (base64 TEXT, survives Render's ephemeral FS).
    """CREATE TABLE IF NOT EXISTS catalogs (
        id          TEXT PRIMARY KEY,
        shop        TEXT,
        name        TEXT,
        config_json TEXT,
        active      INTEGER DEFAULT 0,
        pdf_b64     TEXT,
        pdf_at      TEXT,
        created_at  TEXT,
        updated_at  TEXT
    )""",
    # Campaigns: a named, dated monitoring window over a target (segments / signals / tiers,
    # plus optional hand-picked members held as OPAQUE customer ids — no names/emails/PII).
    # Sales metrics are computed live from the RAM-cached book; only this config is durable.
    """CREATE TABLE IF NOT EXISTS campaigns (
        id          TEXT PRIMARY KEY,
        shop        TEXT,
        name        TEXT,
        starts      TEXT,
        ends        TEXT,
        config_json TEXT,
        created_at  TEXT,
        updated_at  TEXT
    )""",
]
# Earlier versions cached customer PII in these tables. Drop them so any deploy purges it.
_DROP_LEGACY = [
    "DROP TABLE IF EXISTS scores",
    "DROP TABLE IF EXISTS orders",
    "DROP TABLE IF EXISTS dashboards",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_week(when: datetime | None = None) -> str:
    """Current ISO week bucket in UTC, e.g. '2026-W27'. The key metrics roll up by."""
    return (when or datetime.now(timezone.utc)).strftime("%G-W%V")


def _week_of(iso_timestamp: str | None) -> str | None:
    """ISO week bucket of a stored ISO-8601 timestamp string ('2026-07-06T...'), or None."""
    if not iso_timestamp:
        return None
    try:
        return datetime.fromisoformat(iso_timestamp).strftime("%G-W%V")
    except (ValueError, TypeError):
        return None


def recent_weeks(n: int = 8) -> list[str]:
    """The last ``n`` ISO week buckets, oldest first, ending with the current week."""
    from datetime import timedelta

    today = datetime.now(timezone.utc)
    weeks = [( today - timedelta(weeks=i) ).strftime("%G-W%V") for i in range(n)]
    return list(reversed(weeks))


class _DB:
    """Shared backend wrapper: Postgres (pooled) or SQLite, with `:name` param translation."""

    def __init__(self, db_path=None, database_url: str | None = ...):
        url = DATABASE_URL if database_url is ... else database_url
        self.pg = bool(url)
        if self.pg:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            self.pool = ConnectionPool(url, kwargs={"row_factory": dict_row},
                                       min_size=1, max_size=5, open=True)
        else:
            import sqlite3

            path = db_path or DB_PATH
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(path), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        for stmt in (*_DROP_LEGACY, *_TABLES):
            self._run(stmt)

    def _q(self, sql: str) -> str:
        if not self.pg:
            return sql
        return re.sub(r":(\w+)", r"%(\1)s", sql).replace("?", "%s")

    def _run(self, sql: str, params=None, *, fetch: str | None = None):
        q = self._q(sql)
        if self.pg:
            with self.pool.connection() as conn:
                cur = conn.cursor()
                cur.execute(q, params or {})
                return cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else None
        cur = self.conn.cursor()
        cur.execute(q, params or {})
        if fetch:
            return cur.fetchone() if fetch == "one" else cur.fetchall()
        self.conn.commit()
        return None


class ShopStore(_DB):
    """Encrypted, per-shop merchant secrets. Nothing here identifies a customer."""

    # ── Shopify offline token (from token exchange) ─────────────────────────────
    def save_shop(self, shop: str, access_token: str) -> None:
        self._run(
            """INSERT INTO shops (shop, access_token, installed_at)
               VALUES (:shop, :token, :at)
               ON CONFLICT(shop) DO UPDATE SET access_token=excluded.access_token""",
            {"shop": shop, "token": crypto.encrypt(access_token), "at": _now()})

    def get_token(self, shop: str) -> str | None:
        row = self._run("SELECT access_token FROM shops WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        return crypto.decrypt(row["access_token"]) if row else None

    # ── per-shop Klaviyo key (each merchant brings their own) ───────────────────
    def save_klaviyo(self, shop: str, api_key: str) -> None:
        self._run(
            """INSERT INTO klaviyo (shop, api_key, connected_at)
               VALUES (:shop, :key, :at)
               ON CONFLICT(shop) DO UPDATE SET api_key=excluded.api_key,
                connected_at=excluded.connected_at""",
            {"shop": shop, "key": crypto.encrypt(api_key), "at": _now()})

    def get_klaviyo(self, shop: str) -> str | None:
        row = self._run("SELECT api_key FROM klaviyo WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        return crypto.decrypt(row["api_key"]) if row else None

    def delete_klaviyo(self, shop: str) -> None:
        self._run("DELETE FROM klaviyo WHERE shop = :shop", {"shop": shop})

    # ── merchant settings (plain JSON: threshold, email templates, sign-off) ────
    def save_settings(self, shop: str, data_json: str) -> None:
        self._run(
            """INSERT INTO settings (shop, data) VALUES (:shop, :data)
               ON CONFLICT(shop) DO UPDATE SET data=excluded.data""",
            {"shop": shop, "data": data_json})

    def get_settings_raw(self, shop: str) -> str | None:
        row = self._run("SELECT data FROM settings WHERE shop = :shop", {"shop": shop}, fetch="one")
        return row["data"] if row else None

    # ── self-service tenants (WooCommerce etc.) ─────────────────────────────────
    def create_tenant(self, shop: str, kind: str, label: str, token_hash: str) -> None:
        self._run(
            """INSERT INTO tenants (shop, kind, label, token_hash, created_at)
               VALUES (:shop, :kind, :label, :th, :at)
               ON CONFLICT(shop) DO UPDATE SET kind=excluded.kind, label=excluded.label,
                token_hash=excluded.token_hash""",
            {"shop": shop, "kind": kind, "label": label, "th": token_hash, "at": _now()})

    def get_tenant(self, shop: str) -> dict | None:
        return self._run(
            "SELECT shop, kind, label FROM tenants WHERE shop = :shop", {"shop": shop}, fetch="one")

    def tenant_for_token(self, token_hash: str) -> dict | None:
        """Resolve a presented dashboard-link token (already hashed) to its tenant."""
        return self._run("SELECT shop, kind, label FROM tenants WHERE token_hash = :th",
                         {"th": token_hash}, fetch="one")

    def all_tenants(self) -> list[dict]:
        """Every tenant (shop, kind, label). Used to resolve a sign-in email to a shop."""
        return self._run("SELECT shop, kind, label FROM tenants", fetch="all") or []

    # ── WooCommerce REST credentials (encrypted) ────────────────────────────────
    def save_woocommerce(self, shop: str, store_url: str, ck: str, cs: str) -> None:
        self._run(
            """INSERT INTO woocommerce (shop, store_url, consumer_key, consumer_secret, connected_at)
               VALUES (:shop, :url, :ck, :cs, :at)
               ON CONFLICT(shop) DO UPDATE SET store_url=excluded.store_url,
                consumer_key=excluded.consumer_key, consumer_secret=excluded.consumer_secret,
                connected_at=excluded.connected_at""",
            {"shop": shop, "url": store_url, "ck": crypto.encrypt(ck),
             "cs": crypto.encrypt(cs), "at": _now()})

    def get_woocommerce(self, shop: str) -> dict | None:
        row = self._run("SELECT store_url, consumer_key, consumer_secret FROM woocommerce "
                        "WHERE shop = :shop", {"shop": shop}, fetch="one")
        if not row:
            return None
        return {"store_url": row["store_url"],
                "consumer_key": crypto.decrypt(row["consumer_key"]),
                "consumer_secret": crypto.decrypt(row["consumer_secret"])}

    # ── BigCommerce API credentials (store hash + access token, encrypted) ──────
    def save_bigcommerce(self, shop: str, store_hash: str, access_token: str) -> None:
        self._run(
            """INSERT INTO bigcommerce (shop, store_hash, access_token, connected_at)
               VALUES (:shop, :hash, :token, :at)
               ON CONFLICT(shop) DO UPDATE SET store_hash=excluded.store_hash,
                access_token=excluded.access_token, connected_at=excluded.connected_at""",
            {"shop": shop, "hash": store_hash, "token": crypto.encrypt(access_token), "at": _now()})

    def get_bigcommerce(self, shop: str) -> dict | None:
        row = self._run("SELECT store_hash, access_token FROM bigcommerce WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        if not row:
            return None
        return {"store_hash": row["store_hash"],
                "access_token": crypto.decrypt(row["access_token"])}

    # ── Centra Integration-API credentials (base URL + Order:read token, encrypted) ─
    def save_centra(self, shop: str, base_url: str, api_token: str) -> None:
        self._run(
            """INSERT INTO centra (shop, base_url, api_token, connected_at)
               VALUES (:shop, :url, :token, :at)
               ON CONFLICT(shop) DO UPDATE SET base_url=excluded.base_url,
                api_token=excluded.api_token, connected_at=excluded.connected_at""",
            {"shop": shop, "url": base_url, "token": crypto.encrypt(api_token), "at": _now()})

    def get_centra(self, shop: str) -> dict | None:
        row = self._run("SELECT base_url, api_token FROM centra WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        if not row:
            return None
        return {"base_url": row["base_url"],
                "api_token": crypto.decrypt(row["api_token"])}

    # ── SCAYLE Admin-API credentials (base URL + access token, encrypted) ────────────
    def save_scayle(self, shop: str, base_url: str, access_token: str) -> None:
        self._run(
            """INSERT INTO scayle (shop, base_url, access_token, connected_at)
               VALUES (:shop, :url, :token, :at)
               ON CONFLICT(shop) DO UPDATE SET base_url=excluded.base_url,
                access_token=excluded.access_token, connected_at=excluded.connected_at""",
            {"shop": shop, "url": base_url, "token": crypto.encrypt(access_token), "at": _now()})

    def get_scayle(self, shop: str) -> dict | None:
        row = self._run("SELECT base_url, access_token FROM scayle WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        if not row:
            return None
        return {"base_url": row["base_url"],
                "access_token": crypto.decrypt(row["access_token"])}

    # ── order-alert webhook token ───────────────────────────────────────────────
    def get_webhook_token(self, shop: str) -> str | None:
        row = self._run("SELECT token FROM webhooks WHERE shop = :shop", {"shop": shop}, fetch="one")
        return row["token"] if row else None

    def ensure_webhook_token(self, shop: str, token: str) -> str:
        """Store `token` for `shop` if none exists yet; return the effective token."""
        existing = self.get_webhook_token(shop)
        if existing:
            return existing
        self._run("INSERT INTO webhooks (shop, token, created_at) VALUES (:shop, :t, :at) "
                  "ON CONFLICT(shop) DO NOTHING", {"shop": shop, "t": token, "at": _now()})
        return self.get_webhook_token(shop) or token

    def shop_for_webhook(self, token: str) -> str | None:
        row = self._run("SELECT shop FROM webhooks WHERE token = :t", {"t": token}, fetch="one")
        return row["shop"] if row else None

    # ── browser-extension token (store the sha256 hash; rotating replaces it) ────
    def set_extension_token(self, shop: str, token_hash: str) -> None:
        self._run(
            """INSERT INTO extension_tokens (shop, token_hash, created_at)
               VALUES (:shop, :th, :at)
               ON CONFLICT(shop) DO UPDATE SET token_hash=excluded.token_hash,
                created_at=excluded.created_at""",
            {"shop": shop, "th": token_hash, "at": _now()})

    def get_extension_token_hash(self, shop: str) -> str | None:
        row = self._run("SELECT token_hash FROM extension_tokens WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        return row["token_hash"] if row else None

    def shop_for_extension_token(self, token_hash: str) -> str | None:
        row = self._run("SELECT shop FROM extension_tokens WHERE token_hash = :th",
                        {"th": token_hash}, fetch="one")
        return row["shop"] if row else None

    # ── Web Push subscriptions ──────────────────────────────────────────────────
    def add_push_sub(self, shop: str, endpoint: str, p256dh: str, auth: str) -> None:
        self._run(
            """INSERT INTO push_subs (endpoint, shop, p256dh, auth, created_at)
               VALUES (:e, :shop, :p, :a, :at)
               ON CONFLICT(endpoint) DO UPDATE SET shop=excluded.shop, p256dh=excluded.p256dh,
                auth=excluded.auth""",
            {"e": endpoint, "shop": shop, "p": p256dh, "a": auth, "at": _now()})

    def push_subs(self, shop: str) -> list[dict]:
        rows = self._run("SELECT endpoint, p256dh, auth FROM push_subs WHERE shop = :shop",
                         {"shop": shop}, fetch="all") or []
        return [{"endpoint": r["endpoint"], "keys": {"p256dh": r["p256dh"], "auth": r["auth"]}}
                for r in rows]

    def delete_push_sub(self, endpoint: str) -> None:
        self._run("DELETE FROM push_subs WHERE endpoint = :e", {"e": endpoint})

    # ── newsletter ──────────────────────────────────────────────────────────────
    def add_subscriber(self, email: str) -> None:
        self._run(
            """INSERT INTO subscribers (email, subscribed_at) VALUES (:e, :at)
               ON CONFLICT(email) DO NOTHING""",
            {"e": email, "at": _now()})

    # ── lifecycle email journeys + unsubscribe suppression ──────────────────────
    def enroll_journey(self, email: str, journey: str, next_at: str, data_json: str = "{}") -> None:
        """Start ``email`` on ``journey`` due at ``next_at``. Idempotent — an existing enrolment
        (even a completed one) is left as-is so re-submitting a form never restarts a sequence."""
        self._run(
            """INSERT INTO email_journeys (email, journey, step, next_at, data, done,
                                           created_at, updated_at)
               VALUES (:e, :j, 0, :n, :d, 0, :at, :at)
               ON CONFLICT(email, journey) DO NOTHING""",
            {"e": email.strip().lower(), "j": journey, "n": next_at, "d": data_json, "at": _now()})

    def due_journeys(self, now_iso: str) -> list[dict]:
        """Enrolments whose next step is due and not done, excluding unsubscribed emails."""
        rows = self._run(
            """SELECT j.email, j.journey, j.step, j.data FROM email_journeys j
               LEFT JOIN email_suppressions s ON s.email = j.email
               WHERE j.done = 0 AND j.next_at <= :now AND s.email IS NULL""",
            {"now": now_iso}, fetch="all") or []
        return [dict(r) for r in rows]

    def advance_journey(self, email: str, journey: str, step: int, next_at: str) -> None:
        self._run(
            """UPDATE email_journeys SET step = :s, next_at = :n, updated_at = :at
               WHERE email = :e AND journey = :j""",
            {"s": step, "n": next_at, "at": _now(), "e": email.strip().lower(), "j": journey})

    def finish_journey(self, email: str, journey: str) -> None:
        self._run(
            """UPDATE email_journeys SET done = 1, updated_at = :at
               WHERE email = :e AND journey = :j""",
            {"at": _now(), "e": email.strip().lower(), "j": journey})

    def suppress_email(self, email: str, reason: str = "unsubscribe") -> None:
        self._run(
            """INSERT INTO email_suppressions (email, reason, created_at) VALUES (:e, :r, :at)
               ON CONFLICT(email) DO NOTHING""",
            {"e": email.strip().lower(), "r": reason, "at": _now()})

    def is_suppressed(self, email: str) -> bool:
        return bool(self._run("SELECT 1 FROM email_suppressions WHERE email = :e",
                              {"e": (email or "").strip().lower()}, fetch="one"))

    # ── per-shop Mailchimp connection (key + chosen audience) ───────────────────
    def save_mailchimp(self, shop: str, api_key: str, list_id: str, list_name: str) -> None:
        self._run(
            """INSERT INTO mailchimp (shop, api_key, list_id, list_name, connected_at)
               VALUES (:shop, :key, :lid, :lname, :at)
               ON CONFLICT(shop) DO UPDATE SET api_key=excluded.api_key, list_id=excluded.list_id,
                list_name=excluded.list_name, connected_at=excluded.connected_at""",
            {"shop": shop, "key": crypto.encrypt(api_key), "lid": list_id,
             "lname": list_name, "at": _now()})

    def get_mailchimp(self, shop: str) -> dict | None:
        row = self._run("SELECT api_key, list_id, list_name FROM mailchimp WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        if not row:
            return None
        return {"api_key": crypto.decrypt(row["api_key"]),
                "list_id": row["list_id"], "list_name": row["list_name"]}

    def delete_mailchimp(self, shop: str) -> None:
        self._run("DELETE FROM mailchimp WHERE shop = :shop", {"shop": shop})

    # ── per-shop HubSpot connection (encrypted Private App token + portal id) ────
    def save_hubspot(self, shop: str, api_token: str, portal_id: str = "") -> None:
        self._run(
            """INSERT INTO hubspot (shop, api_token, portal_id, connected_at)
               VALUES (:shop, :tok, :pid, :at)
               ON CONFLICT(shop) DO UPDATE SET api_token=excluded.api_token,
                portal_id=excluded.portal_id, connected_at=excluded.connected_at""",
            {"shop": shop, "tok": crypto.encrypt(api_token), "pid": portal_id, "at": _now()})

    def get_hubspot(self, shop: str) -> dict | None:
        row = self._run("SELECT api_token, portal_id FROM hubspot WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        if not row:
            return None
        return {"api_token": crypto.decrypt(row["api_token"]), "portal_id": row["portal_id"] or ""}

    def delete_hubspot(self, shop: str) -> None:
        self._run("DELETE FROM hubspot WHERE shop = :shop", {"shop": shop})

    def save_endear(self, shop: str, api_key: str) -> None:
        self._run(
            """INSERT INTO endear (shop, api_key, connected_at) VALUES (:shop, :key, :at)
               ON CONFLICT(shop) DO UPDATE SET api_key=excluded.api_key,
                connected_at=excluded.connected_at""",
            {"shop": shop, "key": crypto.encrypt(api_key), "at": _now()})

    def get_endear(self, shop: str) -> dict | None:
        row = self._run("SELECT api_key FROM endear WHERE shop = :shop", {"shop": shop}, fetch="one")
        return {"api_key": crypto.decrypt(row["api_key"])} if row else None

    def delete_endear(self, shop: str) -> None:
        self._run("DELETE FROM endear WHERE shop = :shop", {"shop": shop})

    # ── per-shop Slack connection (Incoming Webhook URL, encrypted) ─────────────
    def save_slack(self, shop: str, webhook_url: str, channel: str = "") -> None:
        self._run(
            """INSERT INTO slack (shop, webhook_url, channel, connected_at)
               VALUES (:shop, :url, :ch, :at)
               ON CONFLICT(shop) DO UPDATE SET webhook_url=excluded.webhook_url,
                channel=excluded.channel, connected_at=excluded.connected_at""",
            {"shop": shop, "url": crypto.encrypt(webhook_url), "ch": channel, "at": _now()})

    def get_slack(self, shop: str) -> dict | None:
        row = self._run("SELECT webhook_url, channel FROM slack WHERE shop = :shop",
                        {"shop": shop}, fetch="one")
        if not row:
            return None
        return {"webhook_url": crypto.decrypt(row["webhook_url"]), "channel": row["channel"] or ""}

    def delete_slack(self, shop: str) -> None:
        self._run("DELETE FROM slack WHERE shop = :shop", {"shop": shop})

    # ── site-wide editable content (mini CMS) ───────────────────────────────────
    def get_content_all(self) -> dict:
        rows = self._run("SELECT key, value FROM content", fetch="all") or []
        return {r["key"]: r["value"] for r in rows}

    def set_content(self, key: str, value: str) -> None:
        self._run(
            """INSERT INTO content (key, value, updated_at) VALUES (:k, :v, :at)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            {"k": key, "v": value, "at": _now()})

    def delete_content(self, key: str) -> None:
        self._run("DELETE FROM content WHERE key = :k", {"k": key})

    # ── blog CMS (site-wide company content, not customer data) ──────────────────
    _POST_COLS = ("slug", "title", "dek", "body_html", "author", "cover_image_id",
                  "tags", "status", "published_at", "created_at", "updated_at")

    def _post_where(self, published_only: bool, tag: str | None):
        """Build the shared WHERE clause + params for list/count."""
        clauses, params = [], {}
        if published_only:
            clauses.append("status = 'published'")
        if tag:
            clauses.append("(',' || COALESCE(tags,'') || ',') LIKE :taglike")
            params["taglike"] = f"%,{tag},%"
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def list_posts(self, published_only: bool = True, sort: str = "newest",
                   tag: str | None = None, limit: int = 9, offset: int = 0) -> list[dict]:
        where, params = self._post_where(published_only, tag)
        # Newest-first by published date (fallback to updated_at for drafts), or oldest-first.
        direction = "ASC" if sort == "oldest" else "DESC"
        params.update({"lim": int(limit), "off": int(offset)})
        rows = self._run(
            f"SELECT * FROM blog_posts{where} "
            f"ORDER BY COALESCE(published_at, updated_at) {direction} "
            f"LIMIT :lim OFFSET :off", params, fetch="all") or []
        return [dict(r) for r in rows]

    def count_posts(self, published_only: bool = True, tag: str | None = None) -> int:
        where, params = self._post_where(published_only, tag)
        row = self._run(f"SELECT COUNT(*) AS n FROM blog_posts{where}", params, fetch="one")
        return int((row or {"n": 0})["n"])

    def get_post(self, slug: str) -> dict | None:
        row = self._run("SELECT * FROM blog_posts WHERE slug = :s", {"s": slug}, fetch="one")
        return dict(row) if row else None

    def upsert_post(self, post: dict) -> None:
        now = _now()
        data = {c: post.get(c) for c in self._POST_COLS}
        data["updated_at"] = now
        if not data.get("created_at"):
            data["created_at"] = now
        self._run(
            """INSERT INTO blog_posts
                 (slug,title,dek,body_html,author,cover_image_id,tags,status,published_at,created_at,updated_at)
               VALUES
                 (:slug,:title,:dek,:body_html,:author,:cover_image_id,:tags,:status,:published_at,:created_at,:updated_at)
               ON CONFLICT(slug) DO UPDATE SET
                 title=excluded.title, dek=excluded.dek, body_html=excluded.body_html,
                 author=excluded.author, cover_image_id=excluded.cover_image_id, tags=excluded.tags,
                 status=excluded.status, published_at=excluded.published_at, updated_at=excluded.updated_at""",
            data)

    def delete_post(self, slug: str) -> None:
        self._run("DELETE FROM blog_posts WHERE slug = :s", {"s": slug})

    def save_image(self, data: bytes, mime: str, image_id: str) -> str:
        import base64
        self._run(
            """INSERT INTO blog_images (id, mime, data_b64, created_at)
               VALUES (:id, :mime, :d, :at)
               ON CONFLICT(id) DO UPDATE SET mime=excluded.mime, data_b64=excluded.data_b64""",
            {"id": image_id, "mime": mime,
             "d": base64.b64encode(data).decode("ascii"), "at": _now()})
        return image_id

    def get_image(self, image_id: str) -> dict | None:
        import base64
        row = self._run("SELECT mime, data_b64 FROM blog_images WHERE id = :id",
                        {"id": image_id}, fetch="one")
        if not row:
            return None
        return {"mime": row["mime"], "data": base64.b64decode(row["data_b64"] or "")}

    # ── product catalogs (catalog-PDF builder) ──────────────────────────────────
    def save_catalog(self, catalog_id: str, shop: str, name: str, config_json: str,
                     active: bool = False) -> None:
        now = _now()
        if active:                                   # one active catalog per shop
            self._run("UPDATE catalogs SET active = 0 WHERE shop = :shop", {"shop": shop})
        self._run(
            """INSERT INTO catalogs (id, shop, name, config_json, active, created_at, updated_at)
               VALUES (:id, :shop, :name, :cfg, :active, :at, :at)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, config_json=excluded.config_json,
                active=excluded.active, updated_at=excluded.updated_at""",
            {"id": catalog_id, "shop": shop, "name": name, "cfg": config_json,
             "active": 1 if active else 0, "at": now})

    def get_catalog(self, catalog_id: str) -> dict | None:
        row = self._run(
            "SELECT id, shop, name, config_json, active, pdf_at FROM catalogs WHERE id = :id",
            {"id": catalog_id}, fetch="one")
        return dict(row) if row else None

    def list_catalogs(self, shop: str) -> list[dict]:
        rows = self._run(
            "SELECT id, shop, name, config_json, active, pdf_at, updated_at FROM catalogs "
            "WHERE shop = :shop ORDER BY updated_at DESC", {"shop": shop}, fetch="all") or []
        return [dict(r) for r in rows]

    def delete_catalog(self, catalog_id: str, shop: str) -> None:
        self._run("DELETE FROM catalogs WHERE id = :id AND shop = :shop",
                  {"id": catalog_id, "shop": shop})

    def set_active_catalog(self, catalog_id: str, shop: str) -> None:
        self._run("UPDATE catalogs SET active = 0 WHERE shop = :shop", {"shop": shop})
        self._run("UPDATE catalogs SET active = 1 WHERE id = :id AND shop = :shop",
                  {"id": catalog_id, "shop": shop})

    def active_catalog(self, shop: str) -> dict | None:
        # The active catalogue for sharing. No PDF requirement — the interactive form link renders
        # live, so a merchant can share it the moment they save (before generating a PDF).
        row = self._run(
            "SELECT id, name FROM catalogs WHERE shop = :shop AND active = 1 "
            "ORDER BY updated_at DESC", {"shop": shop}, fetch="one")
        return dict(row) if row else None

    def set_catalog_pdf(self, catalog_id: str, pdf: bytes) -> None:
        import base64
        self._run("UPDATE catalogs SET pdf_b64 = :d, pdf_at = :at WHERE id = :id",
                  {"d": base64.b64encode(pdf).decode("ascii"), "at": _now(), "id": catalog_id})

    def get_catalog_pdf(self, catalog_id: str) -> bytes | None:
        import base64
        row = self._run("SELECT pdf_b64 FROM catalogs WHERE id = :id", {"id": catalog_id},
                        fetch="one")
        if not row or not row["pdf_b64"]:
            return None
        return base64.b64decode(row["pdf_b64"])

    # ── campaigns (monitoring windows; config only, no customer PII) ─────────────
    def save_campaign(self, campaign_id: str, shop: str, name: str, starts: str,
                      ends: str, config_json: str) -> None:
        now = _now()
        self._run(
            """INSERT INTO campaigns (id, shop, name, starts, ends, config_json, created_at, updated_at)
               VALUES (:id, :shop, :name, :s, :e, :cfg, :at, :at)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, starts=excluded.starts,
                ends=excluded.ends, config_json=excluded.config_json, updated_at=excluded.updated_at""",
            {"id": campaign_id, "shop": shop, "name": name, "s": starts, "e": ends,
             "cfg": config_json, "at": now})

    def get_campaign(self, campaign_id: str, shop: str) -> dict | None:
        row = self._run(
            "SELECT id, shop, name, starts, ends, config_json, created_at, updated_at "
            "FROM campaigns WHERE id = :id AND shop = :shop",
            {"id": campaign_id, "shop": shop}, fetch="one")
        return dict(row) if row else None

    def list_campaigns(self, shop: str) -> list[dict]:
        rows = self._run(
            "SELECT id, shop, name, starts, ends, config_json, created_at, updated_at "
            "FROM campaigns WHERE shop = :shop ORDER BY updated_at DESC",
            {"shop": shop}, fetch="all") or []
        return [dict(r) for r in rows]

    def delete_campaign(self, campaign_id: str, shop: str) -> None:
        self._run("DELETE FROM campaigns WHERE id = :id AND shop = :shop",
                  {"id": campaign_id, "shop": shop})

    # ── per-shop subscription state (Stripe) ────────────────────────────────────
    def get_billing(self, shop: str) -> dict | None:
        row = self._run(
            "SELECT shop, status, customer_id, subscription_id FROM billing WHERE shop = :shop",
            {"shop": shop}, fetch="one")
        return dict(row) if row else None

    def billing_shop_for(self, subscription_id: str | None = None,
                         customer_id: str | None = None) -> str | None:
        """Reverse-map a Stripe subscription or customer id back to its shop. Needed for Payment
        Link subscriptions, whose later webhook events don't carry our shop reference."""
        if subscription_id:
            row = self._run("SELECT shop FROM billing WHERE subscription_id = :s",
                            {"s": subscription_id}, fetch="one")
            if row:
                return row["shop"]
        if customer_id:
            row = self._run("SELECT shop FROM billing WHERE customer_id = :c",
                            {"c": customer_id}, fetch="one")
            if row:
                return row["shop"]
        return None

    def set_billing(self, shop: str, status: str, customer_id: str | None = None,
                    subscription_id: str | None = None) -> None:
        self._run(
            """INSERT INTO billing (shop, status, customer_id, subscription_id, updated_at)
               VALUES (:shop, :st, :cid, :sid, :at)
               ON CONFLICT(shop) DO UPDATE SET status=excluded.status,
                customer_id=COALESCE(excluded.customer_id, billing.customer_id),
                subscription_id=COALESCE(excluded.subscription_id, billing.subscription_id),
                updated_at=excluded.updated_at""",
            {"shop": shop, "st": status, "cid": customer_id, "sid": subscription_id, "at": _now()})

    # ── associate feedback (aggregate per-signal tally; no customer data) ───────
    def record_feedback(self, shop: str, signals: list[str], verdict: str) -> None:
        """Increment the fit/nofit tally for each signal that fired on a customer the merchant
        judged. ``verdict`` is 'fit' or 'nofit'. Stores no customer identifier."""
        col = "fit" if verdict == "fit" else "nofit"
        for signal in {s for s in signals if s}:
            self._run(
                f"""INSERT INTO feedback_stats (shop, signal, {col}) VALUES (:shop, :sig, 1)
                    ON CONFLICT(shop, signal) DO UPDATE SET {col} = feedback_stats.{col} + 1""",
                {"shop": shop, "sig": signal})

    def get_feedback_stats(self, shop: str) -> list[dict]:
        rows = self._run("SELECT signal, fit, nofit FROM feedback_stats WHERE shop = :shop",
                         {"shop": shop}, fetch="all") or []
        return [dict(r) for r in rows]

    def feedback_by_shop(self) -> dict[str, dict[str, int]]:
        """{shop: {fit, nofit}} summed across signals (lifetime; per-signal over-count caveat)."""
        rows = self._run("SELECT shop, SUM(fit) AS fit, SUM(nofit) AS nofit FROM feedback_stats "
                         "GROUP BY shop", fetch="all") or []
        return {r["shop"]: {"fit": int(r["fit"] or 0), "nofit": int(r["nofit"] or 0)} for r in rows}

    # ── console-dashboard activity counters (aggregate, per shop + ISO week) ───────
    def bump_metric(self, shop: str, metric: str, n: int = 1, week: str | None = None) -> None:
        """Increment a per-shop, per-week activity counter. Never raises on a zero/negative n."""
        if n <= 0:
            return
        self._run(
            """INSERT INTO metrics (shop, week, metric, count) VALUES (:shop, :week, :metric, :n)
               ON CONFLICT(shop, week, metric) DO UPDATE SET count = metrics.count + :n""",
            {"shop": shop, "week": week or _iso_week(), "metric": metric, "n": int(n)})

    def shop_metric(self, shop: str, metric: str, week: str | None = None) -> int:
        """One shop's count for a metric in a single week bucket (the current ISO week by default).
        Used as a cheap per-tenant, per-week cost guard (e.g. the AI-draft ceiling)."""
        row = self._run(
            "SELECT count FROM metrics WHERE shop = :shop AND week = :week AND metric = :metric",
            {"shop": shop, "week": week or _iso_week(), "metric": metric}, fetch="one")
        return int(row["count"]) if row else 0

    def metric_totals(self, weeks: list[str] | None = None) -> dict[str, int]:
        """Sum each metric across all shops, optionally restricted to a set of week buckets."""
        if weeks:
            placeholders = ",".join(f":w{i}" for i in range(len(weeks)))
            params = {f"w{i}": w for i, w in enumerate(weeks)}
            rows = self._run(
                f"SELECT metric, SUM(count) AS total FROM metrics WHERE week IN ({placeholders}) "
                "GROUP BY metric", params, fetch="all") or []
        else:
            rows = self._run(
                "SELECT metric, SUM(count) AS total FROM metrics GROUP BY metric", fetch="all") or []
        return {r["metric"]: int(r["total"] or 0) for r in rows}

    def metric_weekly(self, metric: str, weeks: list[str]) -> dict[str, int]:
        """Per-week totals (across shops) for one metric, keyed by week (0 for weeks with no rows)."""
        if not weeks:
            return {}
        placeholders = ",".join(f":w{i}" for i in range(len(weeks)))
        params = {f"w{i}": w for i, w in enumerate(weeks)}
        params["metric"] = metric
        rows = self._run(
            f"SELECT week, SUM(count) AS total FROM metrics WHERE metric = :metric "
            f"AND week IN ({placeholders}) GROUP BY week", params, fetch="all") or []
        got = {r["week"]: int(r["total"] or 0) for r in rows}
        return {w: got.get(w, 0) for w in weeks}

    def metric_by_shop(self, weeks: list[str] | None = None) -> dict[str, dict[str, int]]:
        """{shop: {metric: total}} across the given weeks (all-time if None) — per-tenant activity."""
        if weeks:
            placeholders = ",".join(f":w{i}" for i in range(len(weeks)))
            params = {f"w{i}": w for i, w in enumerate(weeks)}
            rows = self._run(
                f"SELECT shop, metric, SUM(count) AS total FROM metrics WHERE week IN "
                f"({placeholders}) GROUP BY shop, metric", params, fetch="all") or []
        else:
            rows = self._run(
                "SELECT shop, metric, SUM(count) AS total FROM metrics GROUP BY shop, metric",
                fetch="all") or []
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["shop"], {})[r["metric"]] = int(r["total"] or 0)
        return out

    # ── console-dashboard overview counts (config/connection data, no new storage) ─
    def count_tenants_by_kind(self) -> dict[str, int]:
        rows = self._run("SELECT kind, COUNT(*) AS n FROM tenants GROUP BY kind", fetch="all") or []
        return {r["kind"]: int(r["n"]) for r in rows}

    def count_shops(self) -> int:
        row = self._run("SELECT COUNT(*) AS n FROM shops", fetch="one")
        return int(row["n"]) if row else 0

    def integration_counts(self) -> dict[str, dict[str, int]]:
        """{integration: {total, this_week}} from each connection table's connected_at."""
        this_week = _iso_week()
        out: dict[str, dict[str, int]] = {}
        for table in ("klaviyo", "mailchimp", "hubspot", "endear", "slack", "woocommerce", "bigcommerce", "centra", "scayle"):
            rows = self._run(f"SELECT connected_at FROM {table}", fetch="all") or []
            total = len(rows)
            recent = sum(1 for r in rows
                         if _week_of(r["connected_at"]) == this_week)
            out[table] = {"total": total, "this_week": recent}
        return out

    def billing_breakdown(self) -> dict[str, int]:
        rows = self._run("SELECT status, COUNT(*) AS n FROM billing GROUP BY status",
                         fetch="all") or []
        return {(r["status"] or "unknown"): int(r["n"]) for r in rows}

    def count_subscribers(self) -> int:
        row = self._run("SELECT COUNT(*) AS n FROM subscribers", fetch="one")
        return int(row["n"]) if row else 0

    def count_push_subs(self) -> int:
        row = self._run("SELECT COUNT(*) AS n FROM push_subs", fetch="one")
        return int(row["n"]) if row else 0

    def new_tenants(self, week: str | None = None) -> int:
        """Tenants whose created_at falls in the given ISO week (this week by default)."""
        target = week or _iso_week()
        rows = self._run("SELECT created_at FROM tenants", fetch="all") or []
        return sum(1 for r in rows if _week_of(r["created_at"]) == target)

    def all_shops(self) -> list[str]:
        """Every Shopify shop domain with a stored offline token (may exceed `tenants`)."""
        rows = self._run("SELECT shop FROM shops", fetch="all") or []
        return [r["shop"] for r in rows]

    def billing_by_shop(self) -> dict[str, str]:
        rows = self._run("SELECT shop, status FROM billing", fetch="all") or []
        return {r["shop"]: (r["status"] or "unknown") for r in rows}

    def integrations_by_shop(self) -> dict[str, list[str]]:
        """{shop: [integration names connected]} across every per-shop connection table."""
        out: dict[str, list[str]] = {}
        for table in ("klaviyo", "mailchimp", "hubspot", "endear", "slack", "woocommerce", "bigcommerce", "centra", "scayle"):
            rows = self._run(f"SELECT shop FROM {table}", fetch="all") or []
            for r in rows:
                out.setdefault(r["shop"], []).append(table)
        return out

    # ── deletion (shop/redact + app/uninstalled) ───────────────────────────────
    def delete_shop(self, shop: str) -> None:
        """Erase everything we hold for a shop — tokens, keys, settings, tenant, Woo, Mailchimp."""
        for table in ("shops", "klaviyo", "settings", "tenants", "woocommerce", "bigcommerce", "centra",
                      "scayle", "mailchimp", "hubspot", "endear", "slack", "webhooks", "push_subs", "billing",
                      "feedback_stats", "metrics", "catalogs"):
            self._run(f"DELETE FROM {table} WHERE shop = :shop", {"shop": shop})
