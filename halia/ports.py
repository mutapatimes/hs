"""The adapter seams — the two ports every surface plugs into.

`CustomerSource` (READ): any platform turns its data into canonical CustomerRecord
dicts (the `LATEST_COLS` contract) the engine can score. Optionally it can also list
orders (order_id -> customer) so the fulfilment surface has a pick list.

`ScoreSink` (WRITE-BACK): the score flows back OUT to a platform so teams see it where
they already work — a Shopify tag/metafield, a Klaviyo/HubSpot property.

Keeping these abstract is what lets "one application, many surfaces" stay honest: the
engine never knows which platform it's talking to, and a new surface is a new adapter,
not a fork of the brain.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator

from halia.schema import ScoreResult


class CustomerSource(ABC):
    """A platform Halia READS customers from."""

    name: str = "source"

    @abstractmethod
    def fetch_all(self) -> Iterable[dict]:
        """Yield canonical customer records (LATEST_COLS + behavioural fields)."""

    def fetch_one(self, identifier: str, by: str = "email") -> dict | None:
        """Fetch a single customer record by email/phone/id (optional)."""
        return None

    def iter_orders(self) -> Iterator[dict]:
        """Yield {order_id, customer_id, email, created_at} for the fulfilment view.

        Default: none. Sources that have order data (Shopify) override this.
        """
        return iter(())


class ScoreSink(ABC):
    """A platform Halia WRITES the score back to."""

    name: str = "sink"

    def push(self, result: ScoreResult) -> None:
        """Write one customer's score to the platform."""
        self.push_many([result])

    @abstractmethod
    def push_many(self, results: Iterable[ScoreResult]) -> None:
        """Write many customers' scores to the platform."""
