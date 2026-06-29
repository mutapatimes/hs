"""CLI batch tool: pull customers from a source, score them, push to sinks.

    python -m halia.sync file --sinks klaviyo --limit 20    # score the local file, push top-20
    python -m halia.sync shopify --sinks shopify            # score live Shopify, write grades back

Zero-retention: this scores in memory and pushes to the chosen sinks — it persists nothing.
(The embedded app is the live product surface; this stays as a dev/ops utility.)
"""
from __future__ import annotations

import argparse

from halia import config
from halia.engine import engine
from halia.ports import CustomerSource, ScoreSink
from halia.schema import ScoreResult

_SINK_REGISTRY = {
    "shopify": ("halia.adapters.shopify_sink", "ShopifySink"),
    "klaviyo": ("halia.adapters.klaviyo_sink", "KlaviyoSink"),
    "hubspot": ("halia.adapters.hubspot_sink", "HubSpotSink"),
}


def pick_source(name: str | None) -> CustomerSource:
    if name == "shopify" or (name is None and config.SHOPIFY_SHOP and config.SHOPIFY_ADMIN_TOKEN):
        from halia.adapters.shopify_source import ShopifySource
        return ShopifySource()
    from halia.adapters.file_source import FileSource
    return FileSource()


def resolve_sinks(names: list[str] | None) -> list[ScoreSink]:
    if not names:
        return []
    out = []
    for n in names:
        if n not in _SINK_REGISTRY:
            raise SystemExit(f"unknown sink '{n}' (choose from {', '.join(_SINK_REGISTRY)})")
        module, cls = _SINK_REGISTRY[n]
        out.append(getattr(__import__(module, fromlist=[cls]), cls)())
    return out


def _push(sinks: list[ScoreSink], results: list[ScoreResult], limit: int | None) -> dict:
    ranked = sorted((r for r in results if r.flagged), key=lambda r: r.score or 0, reverse=True)
    batch = ranked[:limit] if limit else ranked
    pushed = {}
    for sink in sinks:
        try:
            sink.push_many(batch)
            pushed[sink.name] = f"pushed {len(batch)}"
        except Exception as exc:
            pushed[sink.name] = f"error: {exc}"
    return pushed


def run(source: CustomerSource, sink_names: list[str] | None = None,
        limit: int | None = None) -> dict:
    results = engine.score_many(source.fetch_all())
    pushed = _push(resolve_sinks(sink_names), results, limit)
    return {"source": source.name, "scored": len(results),
            "hidden_vics": sum(1 for r in results if r.hidden_vic), "sinks": pushed}


def main() -> None:
    p = argparse.ArgumentParser(prog="halia.sync")
    p.add_argument("target", nargs="?", default=None, help="file | shopify")
    p.add_argument("--sinks", help="comma list to push to, e.g. klaviyo,shopify")
    p.add_argument("--limit", type=int, help="cap how many top customers get pushed")
    args = p.parse_args()
    sink_names = args.sinks.split(",") if args.sinks else None

    source = pick_source(args.target)
    print(f"Halia sync · source={source.name}"
          + (f" · sinks={sink_names}" if sink_names else "")
          + (f" · limit={args.limit}" if args.limit else "") + " ...")
    summary = run(source, sink_names=sink_names, limit=args.limit)
    print(f"  scored {summary['scored']:,} customers · {summary['hidden_vics']:,} hidden VICs")
    print(f"  sinks: {summary['sinks'] or 'none'}  (nothing persisted)")


if __name__ == "__main__":
    main()
