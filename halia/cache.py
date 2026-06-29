"""RAM-only results cache — where scored customers live, briefly, and nowhere else.

Zero-retention means customer PII is never written to disk or database. But re-pulling and
re-scoring a whole store on every page click is slow, so we hold each shop's freshly-scored
results in **process memory** for a short TTL. This dict is never serialised, never persisted,
and is wiped on restart and on any redact/uninstall webhook — so "Halia stores no customer
data at rest" stays literally true.

One process-global instance: `cache`.
"""
from __future__ import annotations

import os
import threading
import time

TTL_SECONDS = int(os.environ.get("HALIA_CACHE_TTL", "300"))


class ResultsCache:
    """Per-shop {results, payload, orders} held in RAM with a short TTL."""

    def __init__(self, ttl: int = TTL_SECONDS):
        self.ttl = ttl
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def set(self, shop: str, results: list, payload: dict, orders: dict) -> None:
        with self._lock:
            self._data[shop] = {"results": results, "payload": payload, "orders": orders,
                                "expires": time.monotonic() + self.ttl}

    def get(self, shop: str) -> dict | None:
        """Return the live entry for a shop, or None if absent/expired."""
        with self._lock:
            entry = self._data.get(shop)
            if not entry:
                return None
            if time.monotonic() > entry["expires"]:
                self._data.pop(shop, None)
                return None
            return entry

    def evict(self, shop: str) -> None:
        """Forget a shop immediately (redact / uninstall)."""
        with self._lock:
            self._data.pop(shop, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# Process-global cache shared by every surface.
cache = ResultsCache()
