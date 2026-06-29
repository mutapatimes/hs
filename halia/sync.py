"""Batch refresh + push: pull customers, score, persist, and write back.

    python -m halia.sync                         # auto source, sinks enabled in config
    python -m halia.sync file                     # force the local spreadsheet source
    python -m halia.sync shopify                   # force the live Shopify source
    python -m halia.sync file --sinks klaviyo --limit 20   # push top-20 to Klaviyo
    python -m halia.sync push --sinks klaviyo --limit 50   # push from the store (no re-score)

This is the loop the whole product hangs off: Source.fetch_all() -> engine.score_many()
-> store.upsert_many() -> every chosen ScoreSink.push_many(). `--limit` caps how many of
the highest-scoring flagged customers get written back (start small for a first live
push). `push` skips scoring and writes the top hidden-VICs already in the store.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from halia import config
from halia.engine import engine
from halia.ports import CustomerSource, ScoreSink
from halia.schema import ScoreResult
from halia.store import ScoreStore

_SINK_REGISTRY = {
    "shopify": ("halia.adapters.shopify_sink", "ShopifySink"),
    "klaviyo": ("halia.adapters.klaviyo_sink", "KlaviyoSink"),
    "hubspot": ("halia.adapters.hubspot_sink", "HubSpotSink"),
}


def pick_source(name: str | None) -> CustomerSource:
    """Explicit source name, else Shopify-if-configured, else the local file."""
    if name == "shopify" or (name is None and config.SHOPIFY_SHOP and config.SHOPIFY_ADMIN_TOKEN):
        from halia.adapters.shopify_source import ShopifySource
        return ShopifySource()
    from halia.adapters.file_source import FileSource
    return FileSource()


def resolve_sinks(names: list[str] | None) -> list[ScoreSink]:
    """Sinks to push to: an explicit --sinks list, else the config-enabled ones."""
    if names is None:
        return enabled_sinks()
    out = []
    for n in names:
        if n not in _SINK_REGISTRY:
            raise SystemExit(f"unknown sink '{n}' (choose from {', '.join(_SINK_REGISTRY)})")
        module, cls = _SINK_REGISTRY[n]
        out.append(getattr(__import__(module, fromlist=[cls]), cls)())
    return out


def enabled_sinks() -> list[ScoreSink]:
    """The write-back sinks switched on in config (Shopify first)."""
    flags = [("klaviyo", config.ENABLE_KLAVIYO_SINK), ("shopify", config.ENABLE_SHOPIFY_SINK),
             ("hubspot", config.ENABLE_HUBSPOT_SINK)]
    return resolve_sinks([n for n, on in flags if on]) if any(on for _, on in flags) else []


def _push(sinks: list[ScoreSink], results: list[ScoreResult], limit: int | None) -> dict:
    """Push the highest-scoring flagged results (capped by limit) to each sink."""
    ranked = sorted((r for r in results if r.flagged), key=lambda r: r.score or 0, reverse=True)
    batch = ranked[:limit] if limit else ranked
    pushed = {}
    for sink in sinks:
        try:
            sink.push_many(batch)
            pushed[sink.name] = f"pushed {len(batch)}"
        except Exception as exc:  # a write-back failure must not lose the scores
            pushed[sink.name] = f"error: {exc}"
    return pushed


def _shop_for(source: CustomerSource) -> str:
    """The tenant key for the store. Live Shopify uses the real domain; file = 'local'."""
    return config.SHOPIFY_SHOP if source.name == "shopify" and config.SHOPIFY_SHOP else "local"


def run(source: CustomerSource, store: ScoreStore | None = None,
        sink_names: list[str] | None = None, limit: int | None = None,
        shop: str | None = None) -> dict:
    store = store or ScoreStore()
    shop = shop or _shop_for(source)
    scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results = engine.score_many(source.fetch_all())
    n_scores = store.upsert_many(results, shop=shop, source=source.name, scored_at=scored_at)
    n_orders = store.upsert_orders(source.iter_orders(), shop=shop)
    pushed = _push(resolve_sinks(sink_names), results, limit)
    return {"source": source.name, "shop": shop, "scored": n_scores, "orders": n_orders,
            "hidden_vics": sum(1 for r in results if r.hidden_vic), "sinks": pushed}


def push_from_store(store: ScoreStore, sink_names: list[str], limit: int | None,
                    shop: str = "local") -> dict:
    """Push the top hidden-VICs already in the store — no re-scoring."""
    results = store.top_hidden(shop, limit or 10_000)
    return {"pushed_from_store": len(results), "sinks": _push(resolve_sinks(sink_names), results, limit)}


def main() -> None:
    p = argparse.ArgumentParser(prog="halia.sync")
    p.add_argument("target", nargs="?", default=None,
                   help="file | shopify | push  (default: auto-detect source)")
    p.add_argument("--sinks", help="comma list to push to, e.g. klaviyo,shopify")
    p.add_argument("--limit", type=int, help="cap how many top customers get pushed")
    args = p.parse_args()
    sink_names = args.sinks.split(",") if args.sinks else None

    if args.target == "push":
        if not sink_names:
            raise SystemExit("push needs --sinks (e.g. --sinks klaviyo)")
        shop = config.SHOPIFY_SHOP or "local"
        summary = push_from_store(ScoreStore(), sink_names, args.limit, shop=shop)
        print(f"Halia push · shop={shop} · {summary['pushed_from_store']:,} from store -> {summary['sinks']}")
        return

    source = pick_source(args.target)
    print(f"Halia sync · source={source.name}"
          + (f" · sinks={sink_names}" if sink_names else "")
          + (f" · limit={args.limit}" if args.limit else "") + " ...")
    summary = run(source, sink_names=sink_names, limit=args.limit)
    print(f"  scored {summary['scored']:,} customers · {summary['hidden_vics']:,} hidden VICs")
    print(f"  orders indexed: {summary['orders']:,}")
    print(f"  sinks: {summary['sinks'] or 'none enabled'}")
    print(f"  store: {config.DB_PATH}")


if __name__ == "__main__":
    main()
