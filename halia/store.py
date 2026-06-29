"""ScoreStore — durable, multi-tenant home for the latest score per customer.

Surfaces that need a fast answer (the embedded dashboard, the fulfilment view, a CRM
widget) read from here instead of re-scoring live. Every row is scoped by `shop` so
many merchants share one database without seeing each other's data.

Two backends behind one interface, chosen by environment:
  - **Postgres** when `DATABASE_URL` is set (Render / production, multi-tenant), and
  - **SQLite** otherwise (local dev + tests, zero-ops; the file is git-ignored via `*.db`).

SQL is written once with `:name` params and lightly translated for psycopg.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from halia.config import DATABASE_URL, DB_PATH
from halia.schema import ScoreResult

_TABLES = [
    """CREATE TABLE IF NOT EXISTS scores (
        shop          TEXT NOT NULL,
        customer_id   TEXT NOT NULL,
        email         TEXT,
        phone         TEXT,
        grade         TEXT,
        tier          TEXT,
        score         INTEGER,
        signal_count  INTEGER,
        reasons       TEXT,
        gesture       TEXT,
        spend         DOUBLE PRECISION,
        hidden_vic    INTEGER,
        signals       TEXT,
        scored_at     TEXT,
        source        TEXT,
        PRIMARY KEY (shop, customer_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_scores_email ON scores(shop, email)",
    "CREATE INDEX IF NOT EXISTS idx_scores_hidden ON scores(shop, hidden_vic, score)",
    """CREATE TABLE IF NOT EXISTS orders (
        shop        TEXT NOT NULL,
        order_id    TEXT NOT NULL,
        customer_id TEXT,
        email       TEXT,
        created_at  TEXT,
        PRIMARY KEY (shop, order_id)
    )""",
    """CREATE TABLE IF NOT EXISTS shops (
        shop         TEXT PRIMARY KEY,
        access_token TEXT,
        installed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS dashboards (
        shop       TEXT PRIMARY KEY,
        payload    TEXT,
        updated_at TEXT
    )""",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _DB:
    """Shared backend wrapper: param translation + thread-safe execution.

    Backend = Postgres when a ``database_url`` is given (defaults to config), else a
    SQLite file at ``db_path`` (tests pass a temp path for isolation). Postgres uses a
    connection POOL (FastAPI runs sync routes in a threadpool, and a psycopg connection
    is not thread-safe); SQLite uses one shared connection (check_same_thread=False).
    """

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
        for stmt in _TABLES:
            self._run(stmt)

    def _q(self, sql: str) -> str:
        if not self.pg:
            return sql
        return re.sub(r":(\w+)", r"%(\1)s", sql).replace("?", "%s")  # :name->%(name)s, ?->%s

    def _run(self, sql: str, params=None, *, fetch: str | None = None, many=None):
        q = self._q(sql)
        if self.pg:
            with self.pool.connection() as conn:  # commits + returns to pool on exit
                cur = conn.cursor()
                if many is not None:
                    cur.executemany(q, many)
                    return None
                cur.execute(q, params or {})
                return cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else None
        cur = self.conn.cursor()
        if many is not None:
            cur.executemany(q, many)
            self.conn.commit()
            return None
        cur.execute(q, params or {})
        if fetch:
            return cur.fetchone() if fetch == "one" else cur.fetchall()
        self.conn.commit()
        return None

    def _exec(self, sql: str, params=None):
        self._run(sql, params)

    def _execmany(self, sql: str, rows: list[dict]):
        self._run(sql, many=rows)

    def fetchone(self, sql: str, params=None):
        return self._run(sql, params, fetch="one")

    def fetchall(self, sql: str, params=None):
        return self._run(sql, params, fetch="all")


class ScoreStore(_DB):
    """The latest score per customer, scoped by shop."""

    # ── writes ────────────────────────────────────────────────────────────────
    def upsert_many(self, results: Iterable[ScoreResult], shop: str,
                    source: str = "", scored_at: str | None = None) -> int:
        scored_at = scored_at or _now()
        rows = [self._to_row(r, shop, source, scored_at) for r in results if r.customer_id]
        if not rows:
            return 0
        self._execmany(
            """INSERT INTO scores
               (shop,customer_id,email,phone,grade,tier,score,signal_count,reasons,
                gesture,spend,hidden_vic,signals,scored_at,source)
               VALUES (:shop,:customer_id,:email,:phone,:grade,:tier,:score,:signal_count,
                :reasons,:gesture,:spend,:hidden_vic,:signals,:scored_at,:source)
               ON CONFLICT(shop,customer_id) DO UPDATE SET
                email=excluded.email, phone=excluded.phone, grade=excluded.grade,
                tier=excluded.tier, score=excluded.score, signal_count=excluded.signal_count,
                reasons=excluded.reasons, gesture=excluded.gesture, spend=excluded.spend,
                hidden_vic=excluded.hidden_vic, signals=excluded.signals,
                scored_at=excluded.scored_at, source=excluded.source""",
            rows,
        )
        return len(rows)

    def upsert_orders(self, orders: Iterable[dict], shop: str) -> int:
        rows = [
            {"shop": shop, "order_id": str(o["order_id"]),
             "customer_id": None if o.get("customer_id") is None else str(o["customer_id"]),
             "email": o.get("email"), "created_at": o.get("created_at")}
            for o in orders if o.get("order_id") is not None
        ]
        if not rows:
            return 0
        self._execmany(
            """INSERT INTO orders (shop,order_id,customer_id,email,created_at)
               VALUES (:shop,:order_id,:customer_id,:email,:created_at)
               ON CONFLICT(shop,order_id) DO UPDATE SET
                customer_id=excluded.customer_id, email=excluded.email,
                created_at=excluded.created_at""",
            rows,
        )
        return len(rows)

    # ── reads (all shop-scoped) ────────────────────────────────────────────────
    def get_by_customer_id(self, shop: str, customer_id: str) -> ScoreResult | None:
        row = self.fetchone(
            "SELECT * FROM scores WHERE shop = :shop AND customer_id = :cid",
            {"shop": shop, "cid": str(customer_id)})
        return self._from_row(row) if row else None

    def get_by_email(self, shop: str, email: str) -> ScoreResult | None:
        row = self.fetchone(
            "SELECT * FROM scores WHERE shop = :shop AND lower(email) = lower(:email) "
            "ORDER BY score DESC LIMIT 1", {"shop": shop, "email": str(email)})
        return self._from_row(row) if row else None

    def top_hidden(self, shop: str, limit: int = 50) -> list[ScoreResult]:
        rows = self.fetchall(
            "SELECT * FROM scores WHERE shop = :shop AND hidden_vic = 1 "
            "ORDER BY score DESC, spend DESC LIMIT :limit",
            {"shop": shop, "limit": int(limit)})
        return [self._from_row(r) for r in rows]

    def count(self, shop: str) -> int:
        row = self.fetchone("SELECT COUNT(*) AS n FROM scores WHERE shop = :shop", {"shop": shop})
        return int(row["n"])

    # ── prerendered dashboard payload (so the embedded view loads instantly) ────
    def save_dashboard(self, shop: str, payload_json: str) -> None:
        self._exec(
            """INSERT INTO dashboards (shop, payload, updated_at)
               VALUES (:shop, :payload, :at)
               ON CONFLICT(shop) DO UPDATE SET payload=excluded.payload,
                updated_at=excluded.updated_at""",
            {"shop": shop, "payload": payload_json, "at": _now()})

    def get_dashboard(self, shop: str) -> str | None:
        row = self.fetchone("SELECT payload FROM dashboards WHERE shop = :shop", {"shop": shop})
        return row["payload"] if row else None

    def score_for_order(self, shop: str, order_id: str) -> ScoreResult | None:
        row = self.fetchone(
            """SELECT s.* FROM orders o JOIN scores s
               ON o.shop = s.shop AND o.customer_id = s.customer_id
               WHERE o.shop = :shop AND o.order_id = :oid""",
            {"shop": shop, "oid": str(order_id)})
        return self._from_row(row) if row else None

    def recent_orders(self, shop: str, limit: int = 100) -> list[dict]:
        rows = self.fetchall(
            """SELECT o.order_id, o.created_at, s.*
               FROM orders o LEFT JOIN scores s
                 ON o.shop = s.shop AND o.customer_id = s.customer_id
               WHERE o.shop = :shop
               ORDER BY (CASE WHEN s.tier IN ('A1','A') THEN 0
                              WHEN s.tier = 'B' THEN 1
                              WHEN s.tier = 'C' THEN 2 ELSE 3 END),
                        s.score DESC, o.created_at DESC
               LIMIT :limit""", {"shop": shop, "limit": int(limit)})
        out = []
        for row in rows:
            out.append({"order_id": row["order_id"], "created_at": row["created_at"],
                        "result": self._from_row(row) if row["customer_id"] else None})
        return out

    # ── row mapping ───────────────────────────────────────────────────────────
    @staticmethod
    def _to_row(r: ScoreResult, shop: str, source: str, scored_at: str) -> dict:
        d = r.to_dict()
        d.update(shop=shop, hidden_vic=int(bool(r.hidden_vic)),
                 signals=json.dumps(r.signals), source=source, scored_at=scored_at)
        return d

    @staticmethod
    def _from_row(row) -> ScoreResult:
        return ScoreResult(
            matched=True, flagged=bool(row["signal_count"]), tier=row["tier"],
            grade=row["grade"], score=row["score"], is_priority=row["tier"] in ("A1", "A"),
            signal_count=row["signal_count"], signals=json.loads(row["signals"] or "[]"),
            reasons=row["reasons"] or "", gesture=row["gesture"] or "", spend=row["spend"] or 0.0,
            hidden_vic=bool(row["hidden_vic"]), customer_id=row["customer_id"],
            email=row["email"], phone=row["phone"])


class ShopStore(_DB):
    """Per-shop install credentials (the offline Admin API token from token exchange)."""

    def save_shop(self, shop: str, access_token: str) -> None:
        self._exec(
            """INSERT INTO shops (shop, access_token, installed_at)
               VALUES (:shop, :token, :at)
               ON CONFLICT(shop) DO UPDATE SET access_token=excluded.access_token""",
            {"shop": shop, "token": access_token, "at": _now()})

    def get_token(self, shop: str) -> str | None:
        row = self.fetchone("SELECT access_token FROM shops WHERE shop = :shop", {"shop": shop})
        return row["access_token"] if row else None
