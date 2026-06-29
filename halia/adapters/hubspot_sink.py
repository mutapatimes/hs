"""HubSpotSink — write the Halia score onto a HubSpot contact (STUB, not lit).

The pattern, proven but dark: a CRM/clienteling team sees the grade on the contact by
mapping each ScoreResult onto HubSpot **contact properties** —

    halia_grade   -> result.grade
    halia_score   -> result.score
    halia_reasons -> result.reasons

via `POST /crm/v3/objects/contacts/batch/upsert` (idProperty=email) on the HubSpot API.
First-time setup also creates the three custom contact properties. Left unimplemented on
purpose — lit only on real demand (`HALIA_ENABLE_HUBSPOT_SINK=1` + `HUBSPOT_TOKEN`), as a
self-contained adapter behind the same `ScoreSink` port.
"""
from __future__ import annotations

from collections.abc import Iterable

from halia.ports import ScoreSink
from halia.schema import ScoreResult

PROPERTY_MAP = {"halia_grade": "grade", "halia_score": "score", "halia_reasons": "reasons"}


class HubSpotSink(ScoreSink):
    name = "hubspot"

    def __init__(self, token: str | None = None):
        from halia import config
        self.token = token or config.HUBSPOT_TOKEN

    def push_many(self, results: Iterable[ScoreResult]) -> None:
        raise NotImplementedError(
            "HubSpotSink is a documented stub. Create the halia_* contact properties "
            "once, then map PROPERTY_MAP via POST /crm/v3/objects/contacts/batch/upsert "
            "(idProperty=email) before enabling HALIA_ENABLE_HUBSPOT_SINK."
        )
