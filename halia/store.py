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
]
# Earlier versions cached customer PII in these tables. Drop them so any deploy purges it.
_DROP_LEGACY = [
    "DROP TABLE IF EXISTS scores",
    "DROP TABLE IF EXISTS orders",
    "DROP TABLE IF EXISTS dashboards",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

    # ── per-shop subscription state (Stripe) ────────────────────────────────────
    def get_billing(self, shop: str) -> dict | None:
        row = self._run(
            "SELECT shop, status, customer_id, subscription_id FROM billing WHERE shop = :shop",
            {"shop": shop}, fetch="one")
        return dict(row) if row else None

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

    # ── deletion (shop/redact + app/uninstalled) ───────────────────────────────
    def delete_shop(self, shop: str) -> None:
        """Erase everything we hold for a shop — tokens, keys, settings, tenant, Woo, Mailchimp."""
        for table in ("shops", "klaviyo", "settings", "tenants", "woocommerce", "mailchimp",
                      "slack", "webhooks", "push_subs", "billing", "feedback_stats"):
            self._run(f"DELETE FROM {table} WHERE shop = :shop", {"shop": shop})
