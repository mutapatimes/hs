"""The dashboard's two AI conveniences: a written client summary, and plain-English filtering.

Both follow the rule the rest of the engine follows — **the model proposes, deterministic code
decides**:

* ``POST /v1/client/summary`` turns the signals a client already fired into one plain sentence.
  It never adds evidence: the prompt gets only the reasons the engine itself produced, and the
  sentence sits above the same evidence tokens the drawer has always shown, so a merchant can read
  the fact behind every clause.

* ``POST /v1/clients/query`` turns "quiet A-tier clients in London" into the filter object the
  Clients view already accepts. It does not search anything. Every value it returns is checked
  against the vocabulary the page sent, so an invented city or segment is dropped rather than
  applied, and the worst case is a filter that matches nothing rather than a client that does not
  exist.

Zero-retention is unchanged: the summary is memoised only inside the shop's RAM cache entry, so it
lives and dies with the scored book it describes.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Body, Depends, HTTPException

from halia import config
from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store

# ── a written "why this client matters" ──────────────────────────────────────────────
_SUMMARY_SYSTEM = (
    "You write one sentence for a luxury retailer's sales associate, explaining why a client "
    "matters, from evidence the scoring engine has already established.\n\n"
    "Use only what you are given. Never add a fact, a place, an employer or a purchase that is not "
    "in the evidence, and never soften or restate the grade as though it were your own judgement. "
    "Lead with what makes them valuable, then the state of the relationship. Two sentences at most, "
    "plain text, no markdown. Do not use em dashes; use commas, colons or periods. Write as though "
    "briefing a colleague who is about to pick up the phone."
)


def _row_by_cid(shop: str, cid: str) -> Optional[dict]:
    """The client's row from the warm book. Warm only: a drawer must never trigger a sync."""
    from halia.cache import cache
    rows = ((cache.get(shop) or {}).get("payload") or {}).get("data") or []
    want = str(cid).rsplit("/", 1)[-1]
    for row in rows:
        if str(row.get("cid")).rsplit("/", 1)[-1] == want:
            return row
    return None


def _summary_prompt(row: dict) -> str:
    lines = [f"Client: {row.get('name') or 'this client'}"]
    if row.get("grade"):
        lines.append(f"Halia grade: {row['grade']}")
    if row.get("latent"):
        lines.append(f"Estimated latent value: {row['latent']}")
    if row.get("spend") is not None:
        lines.append(f"Spent to date: {row['spend']}")
    if row.get("ordersCount"):
        lines.append(f"Orders: {row['ordersCount']}")
    if row.get("last"):
        lines.append(f"Last order: {row['last']}")
    if row.get("band"):
        lines.append(f"Behaviour: {row['band']}")
    if not row.get("known"):
        lines.append("Not tagged a VIP by the store: this value is unrecognised so far.")
    reasons = [s.get("d") for s in (row.get("signals") or []) if s.get("d")][:8]
    if reasons:
        lines.append("Evidence the engine established:\n" + "\n".join(f"- {r}" for r in reasons))
    lines.append("\nWrite the sentence now.")
    return "\n".join(lines)


# ── plain-English filtering ──────────────────────────────────────────────────────────
_QUERY_SYSTEM = (
    "You translate a retailer's question about their client list into the filter the list already "
    "supports. You are not searching and you cannot name a client: you only choose filter values.\n\n"
    "Use only values from the vocabularies given to you. If part of the question has no matching "
    "filter, put those words in `query` so the list's own text search handles them, and say so in "
    "`explain`. If a part cannot be expressed at all, leave the field at its default and say that "
    "too. Never guess a city or a segment that was not listed.\n\n"
    "`explain` is one short line telling the user what you applied, in their words."
)

_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "string"},
        "play": {"type": "string", "enum": ["", "sleeping", "fresh"]},
        "city": {"type": "string"},
        "segments": {"type": "array", "items": {"type": "string"}},
        "minSignals": {"type": "integer"},
        "sort": {"type": "string", "enum": ["score", "count", "latent", "last"]},
        "query": {"type": "string"},
        "explain": {"type": "string"},
    },
    "required": ["grade", "play", "city", "segments", "minSignals", "sort", "query", "explain"],
    "additionalProperties": False,
}

_GRADES = ("all", "A*", "A", "B", "C")


def _clean_filter(got: dict, cities: list[str], segments: list[str]) -> dict:
    """Keep only values the page can actually apply.

    This is the line between a suggestion and an instruction: anything outside the vocabulary the
    page sent is dropped, so a mistaken city silently becomes "all" rather than an empty list the
    user cannot explain."""
    city_set = {c.lower(): c for c in cities}
    seg_set = {s.lower(): s for s in segments}
    grade = str(got.get("grade") or "all")
    city = str(got.get("city") or "all")
    try:
        min_signals = max(0, min(int(got.get("minSignals") or 0), 5))
    except (TypeError, ValueError):
        min_signals = 0
    segs = [seg_set[str(s).lower()] for s in (got.get("segments") or [])
            if str(s).lower() in seg_set]
    return {
        "grade": grade if grade in _GRADES else "all",
        "play": got.get("play") if got.get("play") in ("", "sleeping", "fresh") else "",
        "city": city_set.get(city.lower(), "all"),
        "segments": segs,
        "minSignals": min_signals,
        "sort": got.get("sort") if got.get("sort") in ("score", "count", "latent", "last") else "score",
        "query": str(got.get("query") or "")[:120],
        "explain": str(got.get("explain") or "")[:200],
    }


def register(app) -> None:

    @app.post("/v1/client/summary")
    def client_summary(shop: str = Depends(require_shop),
                       payload: Any = Body(default=None)) -> dict:
        """One plain sentence on why a client matters, from evidence the engine already found.

        Memoised in the shop's RAM cache entry, so opening the same drawer repeatedly costs one
        call per client per cache lifetime rather than one per click."""
        from halia import llm
        from halia.cache import cache

        body = payload or {}
        cid = str(body.get("cid") or "").strip()
        if not cid:
            raise HTTPException(422, "cid is required")
        if not llm.available():
            return {"summary": "", "source": "none", "ai_available": False}

        key = f"summary:{cid}"
        cached = cache.get_note(shop, key)
        if cached is not None:
            return {"summary": cached, "source": "cache", "ai_available": True}

        row = _row_by_cid(shop, cid)
        if row is None:
            return {"summary": "", "source": "none", "ai_available": True}

        cap = config.LLM_WEEKLY_CAP
        used = shop_store().shop_metric(shop, "insight_summary_ai") if cap else 0
        if cap and used >= cap:
            return {"summary": "", "source": "capped", "ai_available": True}

        text = llm.complete(_SUMMARY_SYSTEM, _summary_prompt(row),
                            model=llm.model_for(row.get("tier")), max_tokens=200)
        if not text:
            return {"summary": "", "source": "none", "ai_available": True}
        cache.set_note(shop, key, text)
        data.record_activity(shop, "insight_summary_ai")
        return {"summary": text, "source": "ai", "ai_available": True}

    @app.post("/v1/clients/query")
    def clients_query(shop: str = Depends(require_shop),
                      payload: Any = Body(default=None)) -> dict:
        """Turn a plain-English question into the Clients view's own filter values.

        The page sends the vocabularies it can actually apply (its cities and signal segments);
        anything outside them is dropped here, so the worst case is a filter that matches nothing
        rather than one the user cannot account for."""
        from halia import llm

        body = payload or {}
        question = str(body.get("q") or "").strip()[:300]
        if not question:
            raise HTTPException(422, "q is required")
        cities = [str(c) for c in (body.get("cities") or [])][:200]
        segments = [str(s) for s in (body.get("segments") or [])][:60]
        if not llm.available():
            return {"ok": False, "reason": "no-ai", "ai_available": False}

        cap = config.LLM_WEEKLY_CAP
        used = shop_store().shop_metric(shop, "insight_query_ai") if cap else 0
        if cap and used >= cap:
            return {"ok": False, "reason": "capped", "ai_available": True}

        prompt = (
            f"Question: {question}\n\n"
            f"Grades: {', '.join(_GRADES)}\n"
            f"Plays: (blank) = everyone, sleeping = proven clients gone quiet, fresh = new "
            f"potential VICs\n"
            f"Signal segments: {', '.join(segments) or '(none)'}\n"
            f"Cities: {', '.join(cities) or '(none)'}\n"
            f"Sorts: score, count (number of signals), latent (estimated value), last (recency)\n\n"
            "Choose the filter values."
        )
        got = llm.structured(_QUERY_SYSTEM, prompt, _QUERY_SCHEMA, max_tokens=600)
        if not got:
            return {"ok": False, "reason": "failed", "ai_available": True}
        data.record_activity(shop, "insight_query_ai")
        return {"ok": True, "filter": _clean_filter(got, cities, segments), "ai_available": True}
