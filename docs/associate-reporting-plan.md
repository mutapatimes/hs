# Associate performance reporting (built 2026-08-27)

**Shipped**: `GET /v1/reports/associates?days=` (halia/api/reports.py) and the Overview "Team performance" toggle (remembered per browser) with a 7/30/90-day table: contacts, clients, A*/A share, owned, converted, rate, revenue, plus a "Shared sign-in" row for unattributed activity. Captures per seat and the weekly manager digest remain future work.

The ask (2026-08-27): a dashboard that tracks each sales associate's performance: how many
messages they send, to whom, and their conversion rate.

## What already exists to build on
- Every seat has an identity: email (unique per shop), name, position, sign-off
  (`seats` table; `GET/POST /v1/extension/profile`).
- Every "contacted" action from the extension or the iPhone app writes an activity entry into
  the client's `halia.pipeline` metafield in the merchant's Shopify, now with `actor_id = seat id`
  and the actor's name (`append_activity` in halia/api/board.py). Nothing is stored on Halia.
- Campaign monitoring already matches orders to activity windows (halia/api/campaigns.py), which
  is the same shape as "did a contact convert".

## Metrics (all derived at view time from the merchant's own Shopify; zero retention holds)
- **Messages sent** per associate per period: count of `contacted` activity entries by `actor_id`.
- **Who**: the clients behind those entries, with grade mix (how much of their outreach goes to
  A* and A clients versus C).
- **Conversion**: an order by that client within N days (default 14) after a contact → attributed
  to the associate who made the most recent contact. Rate = converting contacts ÷ contacts.
- **Revenue influenced**: the value of those orders. Plus captures made (`halia.capture`
  metafield `seat_id`) and their grades.

## Build shape
1. `GET /v1/reports/associates?from=&to=` (require_shop): walk the shop's pipeline metafields
   (bulk query over customers with `metafield halia.pipeline`), fold activity by `actor_id`, join
   with the seat list for names, join orders by customer + window for conversions. Cache the
   result in RAM for the session like everything else.
2. A **Reports** page in the dashboard: a table per associate (messages, clients, A*/A share,
   conversions, rate, revenue), a period picker, a per-associate drill-down listing the clients
   and outcomes.
3. Later: a weekly digest to the manager (journeys already run hourly), and the same numbers on
   the iPhone desk for the associate ("your week").

## Caveats to design for
- Attribution needs the seat: shared-token installs log `actor_id = None`; the report shows
  them as "shared sign-in". Push teams onto seats (the Team panel already does).
- Metafield reads scale with book size; the bulk query is the way, with the same paging the
  campaign monitor uses.
- Keep it honest about causality: "converted after contact" is the label, not "because of".
