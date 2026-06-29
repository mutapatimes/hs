# Halia architecture — one brain, many surfaces

Halia's score is *horizontal*: a clienteling manager wants it in their CRM, a marketer
in Klaviyo/HubSpot, and **fulfilment wants it to prioritise the parcel and add a
discreet touch**. So the score must flow wherever a human makes a decision about a
client — not be locked inside one platform's app.

The design: **separate the brain from the wrapper**. One tool-agnostic scoring engine
in the middle; platforms are thin adapters hanging off two ports.

```
        CustomerSource (READ)                          ScoreSink (WRITE-BACK)
  Shopify ─┐                                  ┌─ Shopify  (metafield `halia.*` + tag `Halia:{grade}`)
  File   ──┤── records ─▶ HaliaEngine ─▶ ─────┤─ Klaviyo  (profile property)   [stub]
  Klaviyo ─┘  (LATEST_COLS)  (scoring/)  results └─ HubSpot (contact property)  [stub]
                                 │
                                 ▼
                           ScoreStore (SQLite)
                                 │
                    FastAPI query API  ◀── fulfilment view (/fulfilment)
        POST /v1/score · GET /v1/score · GET /v1/orders/{id}/score · GET /v1/hidden-vics
```

## Layers

- **Brain — `scoring/`** (unchanged): `score_customers` + the signals + grading. The
  intelligence. Never knows which platform it's talking to.
- **Engine facade — `halia/engine.py`**: `HaliaEngine.score_one/score_many` → the
  canonical `ScoreResult` (`halia/schema.py`). The one entry every surface shares, so
  the till, the dashboard, the API and the write-back can never disagree.
- **Store — `halia/store.py`**: SQLite, the latest `ScoreResult` per customer + an
  order→customer index. Fast reads for surfaces (fulfilment, dashboard, CRM widgets).
- **Query API — `halia/api/app.py`** (FastAPI): the one consistent way to ask "what's
  this client's score, and why." `POST /v1/score` scores live; the GETs read the store.
- **Ports — `halia/ports.py`**: `CustomerSource` (read) and `ScoreSink` (write-back).
  The seams that keep "many surfaces" honest — a new surface is a new adapter, not a
  fork of the brain.
- **Sync — `halia/sync.py`**: `Source.fetch_all() → engine.score_many() →
  store.upsert_many() → enabled Sink.push_many()`. Run on a schedule (or per-customer
  from a webhook) to keep scores live.

## Surfaces — lit one at a time (by proven demand)

| Surface | Status | Notes |
|---|---|---|
| **Shopify** (read) | ✅ lit | reuses `scoring/shopify_fetch` — `halia/adapters/shopify_source.py` |
| **Shopify** (write-back) | ✅ lit | `halia/adapters/shopify_sink.py` — `metafieldsSet` + `tagsAdd`; needs `write_customers` scope; `HALIA_ENABLE_SHOPIFY_SINK=1` |
| **Fulfilment view** | ✅ lit | `GET /fulfilment` — today's orders, priority-first, with the gesture |
| **File** (offline/demo) | ✅ lit | `halia/adapters/file_source.py` — runs the whole pipeline with no creds |
| **Klaviyo** | 🔶 stub | `klaviyo_sink.py` — documented property mapping; lit on demand |
| **HubSpot** | 🔶 stub | `hubspot_sink.py` — documented property mapping; lit on demand |

The discipline: the engine is multi-surface from day one (so we never rip it apart),
but rooms are lit one at a time. Klaviyo/HubSpot stay dark until a real customer turns
them on (`HALIA_ENABLE_*_SINK` + credentials).

## Run it

```bash
pip install -r requirements.txt
python -m halia.sync file                 # score local data → SQLite (no creds)
uvicorn halia.api.app:app --port 8000     # the query API
open http://localhost:8000/fulfilment     # the fulfilment pick list
# live Shopify (custom-app token + write_customers):
#   SHOPIFY_SHOP=… SHOPIFY_ADMIN_TOKEN=… HALIA_ENABLE_SHOPIFY_SINK=1 python -m halia.sync shopify
```

Config (env, `.env` auto-loaded): `HALIA_DB_PATH`, `HALIA_VIC_THRESHOLD`,
`SHOPIFY_SHOP`/`SHOPIFY_ADMIN_TOKEN`, `HALIA_ENABLE_{SHOPIFY,KLAVIYO,HUBSPOT}_SINK`.
See `halia/config.py`.
