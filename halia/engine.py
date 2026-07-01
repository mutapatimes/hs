"""HaliaEngine — the single entry point to the scoring brain.

Every surface (the API, the POS lookup, the batch sync, the write-back sinks) goes
through this facade so they all score identically. It is a thin wrapper over
`scoring.combine.score_customers`; the intelligence lives in `scoring/`, this just
gives it one clean, tool-agnostic shape: records in → `ScoreResult`s out.
"""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from halia.schema import ScoreResult, normalize_record
from scoring.combine import VIC_SPEND_THRESHOLD, score_customers


class HaliaEngine:
    """Score one customer or many, returning the canonical `ScoreResult`."""

    def __init__(self, vic_threshold: float = VIC_SPEND_THRESHOLD,
                 weights: dict[str, int] | None = None):
        self.vic_threshold = vic_threshold
        # Optional per-merchant calibrated weights (see scoring.calibrate). None = defaults.
        self.weights = weights

    def score_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score a whole frame (adds signal_score/count/reasons/hidden_vic)."""
        return score_customers(df, weights=self.weights, vic_threshold=self.vic_threshold)

    def results_from_scored(self, scored: pd.DataFrame) -> list[ScoreResult]:
        """Turn an already-scored frame into ScoreResults (one per row)."""
        return [ScoreResult.from_scored_row(row) for _, row in scored.iterrows()]

    def score_one(self, record: dict | pd.Series) -> ScoreResult:
        """Score a single customer record."""
        scored = self.score_frame(pd.DataFrame([normalize_record(record)]))
        return ScoreResult.from_scored_row(scored.iloc[0])

    def score_many(self, records: Iterable[dict | pd.Series]) -> list[ScoreResult]:
        """Score many customer records."""
        rows = [normalize_record(r) for r in records]
        if not rows:
            return []
        return self.results_from_scored(self.score_frame(pd.DataFrame(rows)))


# Process-wide default engine + module-level conveniences (the common path).
engine = HaliaEngine()


def score_one(record: dict | pd.Series) -> ScoreResult:
    return engine.score_one(record)


def score_many(records: Iterable[dict | pd.Series]) -> list[ScoreResult]:
    return engine.score_many(records)
