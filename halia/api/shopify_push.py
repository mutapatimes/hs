"""Per-shop Shopify write-back — tag scored customers + set Halia metafields, from the dashboard.

Reads the scored customers from the RAM cache (never a database) and writes them back into the
merchant's own Shopify via the ShopifySink (Admin GraphQL `tagsAdd` + `metafieldsSet`), so the
Halia grade shows up where they already work — customer tags, segments, Flow, POS.

Requires the `write_customers` scope on the shop's token. A read-only token (older installs) yields
a clear "reconnect with write_customers" message rather than a 500.

    POST /v1/shopify/push {customer_ids?} — tag all hidden VICs, or a chosen few
"""
from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, HTTPException

from halia.api import data
from halia.api.shopify_auth import require_shop, shop_store


def _entry_or_404(shop: str) -> dict:
    entry = data.results_for(shop)
    if entry is None:
        raise HTTPException(404, "No scored data for this shop yet — open the dashboard first.")
    return entry


# ---- The Halia tag vocabulary (Shopify Flow builds conditions against these exact strings) ----
# Grade tags follow the sink's existing format (Halia:A*, Halia:A). Play tags are the moving
# parts: they appear when a play is detected and are REMOVED when it clears, so Flow's native
# "Customer tag added" trigger fires exactly at the moment the play begins.
PLAY_TAG_GONE_QUIET = "Halia:GoneQuiet"
PLAY_TAG_FRESH = "Halia:Fresh"
PLAY_TAGS = frozenset({PLAY_TAG_GONE_QUIET, PLAY_TAG_FRESH})
AUTO_PUSH_CAP = 500   # max customers written per sync — keeps a first sync from hammering the API


def play_tags(row: dict) -> set[str]:
    """The Halia tags one dashboard payload row should carry in Shopify.

    Mirrors the template's playOf(): sleeping = a proven known client, or an A-tier hidden VIC
    with 2+ orders that lapsed; fresh = a hidden VIC whose activity is recent or brand new.
    """
    tags: set[str] = set()
    a_tier = row.get("tier") in ("A1", "A")
    if a_tier and row.get("grade"):
        tags.add(f"Halia:{row['grade']}")
    band = row.get("band")
    if row.get("known") or (a_tier and (row.get("ordersCount") or 0) >= 2 and band == "lapsed"):
        tags.add(PLAY_TAG_GONE_QUIET)
    elif not row.get("known") and band in ("active", "new"):
        tags.add(PLAY_TAG_FRESH)
    return tags


def desired_tag_map(payload: dict) -> dict[str, set[str]]:
    """{customer_id: halia tags} for every payload row with a real Shopify customer id."""
    out: dict[str, set[str]] = {}
    for row in (payload or {}).get("data") or []:
        cid = str(row.get("cid") or "").strip()
        if not cid:
            continue
        tags = play_tags(row)
        if tags:
            out[cid] = tags
    return out


def maybe_auto_push(shop: str, token: str, entry: dict, prev_entry: dict | None) -> None:
    """Opt-in, best-effort tag sync after a Shopify score sync (the Shopify Flow integration).

    Diffs the fresh payload's tag map against the previous cache entry's: new tags are added,
    cleared PLAY tags are removed (grade tags only ever accumulate upward), and a customer who
    left the surfaced set has their play tags removed. First sync after a restart pushes the
    full map (tagsAdd is idempotent). Never raises: a write failure must not fail the sync.
    """
    import logging
    log = logging.getLogger("halia.autopush")
    try:
        from halia.api.settings import settings_for
        if not settings_for(shop).get("shopify_auto_push"):
            return
        from halia.api import billing
        if not billing.is_paid(shop):
            return                                   # teaser tenants read; paid tenants write
        desired = desired_tag_map(entry.get("payload") or {})
        previous = desired_tag_map((prev_entry or {}).get("payload") or {})
        ops: list[tuple[str, list[str], list[str]]] = []     # (cid, add, remove)
        for cid, want in desired.items():
            had = previous.get(cid, set())
            add = sorted(want - had) if previous else sorted(want)
            remove = sorted((had - want) & PLAY_TAGS)
            if add or remove:
                ops.append((cid, add, remove))
        for cid, had in previous.items():
            gone = sorted(had & PLAY_TAGS)
            if cid not in desired and gone:
                ops.append((cid, [], gone))
        if not ops:
            return
        dropped = max(0, len(ops) - AUTO_PUSH_CAP)
        ops = ops[:AUTO_PUSH_CAP]
        from halia.adapters.shopify_sink import ShopifySink
        from scoring.shopify_fetch import http_transport
        sink = ShopifySink(transport=http_transport(shop, token))
        written = 0
        for cid, add, remove in ops:
            try:
                if add:
                    sink.tag_customer(cid, add)
                if remove:
                    sink.untag_customer(cid, remove)
                written += 1
            except Exception as exc:  # noqa: BLE001 — one bad customer must not stop the batch
                log.warning("auto-push failed for %s: %s", cid, exc)
        if written:
            data.record_activity(shop, "action_shopify_autopush", written)
        if dropped:
            log.warning("auto-push for %s capped at %d customers (%d deferred to the next sync)",
                        shop, AUTO_PUSH_CAP, dropped)
    except Exception as exc:  # noqa: BLE001 — the sync result is sacred; tagging is best-effort
        log.warning("auto-push skipped for %s: %s", shop, exc)


def register(app) -> None:

    @app.post("/v1/shopify/push")
    def shopify_push(shop: str = Depends(require_shop), payload: Any = Body(None)) -> dict:
        """Write `Halia:{grade}` tags + `halia.*` metafields back to the shop's customers."""
        store = shop_store()
        tenant = store.get_tenant(shop)
        if tenant and tenant["kind"] in ("woocommerce", "bigcommerce"):
            raise HTTPException(400, "Tagging back is a Shopify feature — this store is not on Shopify.")
        token = store.get_token(shop)
        if not token:
            raise HTTPException(400, "No Shopify connection for this store.")

        entry = _entry_or_404(shop)
        ids = (payload or {}).get("customer_ids") if isinstance(payload, dict) else None
        results = [data.result_by_id(entry, c) for c in ids] if ids else data.hidden_results(entry)
        targets = [r for r in results if r and r.flagged and r.customer_id]
        if not targets:
            return {"pushed": 0}

        from halia.adapters.shopify_sink import ShopifySink
        from scoring.shopify_fetch import ShopifyError, http_transport

        try:
            sink = ShopifySink(transport=http_transport(shop, token))
            sink.push_many(targets)
            # Play tags ride along with the grade tags, so Flow recipes work from a manual
            # push too (best-effort: a play-tag miss must not undo a successful grade push).
            tagmap = desired_tag_map(entry.get("payload") or {})
            for r in targets:
                extra = sorted(tagmap.get(str(r.customer_id), set()) & PLAY_TAGS)
                if extra:
                    try:
                        sink.tag_customer(str(r.customer_id), extra)
                    except Exception:  # noqa: BLE001
                        pass
        except ShopifyError as exc:
            msg = str(exc)
            if any(t in msg.lower() for t in ("write_customers", "scope", "access denied", "403")):
                raise HTTPException(
                    400, "Reconnect Shopify with the write_customers permission to tag customers.")
            raise HTTPException(502, f"Shopify rejected the write: {msg}")
        data.record_activity(shop, "action_shopify_push", len(targets))
        return {"pushed": len(targets)}
