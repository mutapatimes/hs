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

# The policy, as published: a scored book is held in memory while the store is in use and
# released within an hour of its last use; never written to disk. "Fresh" for TTL_SECONDS after
# scoring, then served stale once while a new pull runs behind the page; evicted IDLE_SECONDS
# after the last real use (a page or an API read), whatever its age. The hourly warm-up only
# re-scores stores opened in the last WARM_HOURS, and its freshness check does not count as use.
TTL_SECONDS = int(os.environ.get("HALIA_CACHE_TTL", "3600"))
IDLE_SECONDS = int(os.environ.get("HALIA_CACHE_IDLE", "3600"))
WARM_HOURS = int(os.environ.get("HALIA_WARM_HOURS", "12"))


class ResultsCache:
    """Per-shop {results, payload, orders} held in RAM with a short TTL."""

    def __init__(self, ttl: int = TTL_SECONDS, idle: int = IDLE_SECONDS):
        self.ttl = ttl
        self.idle = idle
        self._data: dict[str, dict] = {}
        self._alerts: dict[str, list] = {}   # per-shop recent high-grade order alerts (RAM)
        self._lock = threading.Lock()

    # ── live order alerts (RAM-only, capped) ───────────────────────────────────
    def add_alert(self, shop: str, alert: dict, cap: int = 50) -> None:
        with self._lock:
            buf = self._alerts.setdefault(shop, [])
            if any(a.get("order_id") == alert.get("order_id") for a in buf):
                return
            buf.insert(0, alert)
            del buf[cap:]

    def get_alerts(self, shop: str) -> list:
        with self._lock:
            return list(self._alerts.get(shop, []))

    def set(self, shop: str, results: list, payload: dict, orders: dict,
            full: dict | None = None) -> None:
        """``full`` is the unmasked book when ``payload`` is the free-scan (masked) view of it, so
        a comp or a plan can take effect at once rather than after another scoring run. The scored
        results and orders in the same entry are already unmasked, so this widens nothing."""
        with self._lock:
            now = time.monotonic()
            self._data[shop] = {"results": results, "payload": payload, "orders": orders,
                                "full": full if full is not None else payload,
                                "expires": now + self.ttl, "evict": now + self.idle}

    def unmask(self, shop: str) -> bool:
        """Swap the unmasked book in for a masked one, in place, so anyone holding the entry sees
        it. True when done; False when there is no entry or no unmasked book to swap in."""
        with self._lock:
            entry = self._live(shop, time.monotonic())
            if entry is None:
                return False
            full = entry.get("full")
            if not full or not (entry.get("payload") or {}).get("masked") or full.get("masked"):
                return False
            entry["payload"] = full
            return True

    def _live(self, shop: str, now: float) -> dict | None:
        """The entry if it has not passed its idle eviction; drops it if it has. Lock held."""
        entry = self._data.get(shop)
        if not entry:
            return None
        if now > entry.get("evict", entry["expires"]):
            self._data.pop(shop, None)
            return None
        return entry

    def get(self, shop: str) -> dict | None:
        """The fresh entry for a shop, or None if absent, idle too long, or past its TTL. A hit is
        a use: it keeps the book in memory for another idle window."""
        with self._lock:
            now = time.monotonic()
            entry = self._live(shop, now)
            if entry is None:
                return None
            entry["evict"] = max(entry["evict"], now + self.idle)
            return entry if now <= entry["expires"] else None

    def get_stale(self, shop: str) -> dict | None:
        """The last scored book, fresh or not, so a page can show it while a new pull runs. A hit
        is a use. None once idle has evicted it or it was never there."""
        with self._lock:
            now = time.monotonic()
            entry = self._live(shop, now)
            if entry is not None:
                entry["evict"] = max(entry["evict"], now + self.idle)
            return entry

    def peek(self, shop: str) -> str | None:
        """'fresh', 'stale' or None, without counting as a use. For the warm-up, whose checks must
        never keep a book alive by themselves."""
        with self._lock:
            now = time.monotonic()
            entry = self._live(shop, now)
            if entry is None:
                return None
            return "fresh" if now <= entry["expires"] else "stale"

    # ── memoised derived text (a written client summary) ──────────────────────
    # Kept inside the shop's own entry so it inherits the same TTL and the same eviction: when the
    # scored book goes, anything written about it goes with it. Nothing new is persisted.
    def get_note(self, shop: str, key: str) -> str | None:
        entry = self.get(shop)
        if not entry:
            return None
        with self._lock:
            return (entry.get("notes") or {}).get(key)

    def set_note(self, shop: str, key: str, value: str, cap: int = 500) -> None:
        entry = self.get(shop)
        if not entry:
            return
        with self._lock:
            notes = entry.setdefault("notes", {})
            if len(notes) >= cap:
                notes.clear()          # a whole book's worth: start again rather than grow forever
            notes[key] = value

    def evict(self, shop: str) -> None:
        """Forget a shop immediately (redact / uninstall)."""
        with self._lock:
            self._data.pop(shop, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


# Process-global cache shared by every surface.
cache = ResultsCache()
