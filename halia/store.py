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

    # ── deletion (shop/redact + app/uninstalled) ───────────────────────────────
    def delete_shop(self, shop: str) -> None:
        """Erase everything we hold for a shop — its token and Klaviyo key."""
        self._run("DELETE FROM shops WHERE shop = :shop", {"shop": shop})
        self._run("DELETE FROM klaviyo WHERE shop = :shop", {"shop": shop})
