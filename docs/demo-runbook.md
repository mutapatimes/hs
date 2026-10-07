# Demo runbook: the Maison Aurelle store

Maison Aurelle is Halia's fictional luxury house: a Shopify development store holding about 1,500
synthetic clients, two years of orders and a twelve-piece catalogue, scored by the real engine.
It is for screen-share demos and for app review. Nobody in it exists.

## Building the store (once, about 90 minutes)

1. Partner Dashboard → Stores → Add store → Development store. Name "Maison Aurelle", purpose
   "test an app", a London address, GBP. No Plus features needed.
2. Dev Dashboard → Create app → manually → "Seeder" (or, in older admins, the store's Settings → Apps and sales channels → Develop apps).
   Admin API scopes: write_customers, write_orders, write_products, read_customers, read_products.
   Release it and install it on the dev store; the seeder takes the app's client id and secret (SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET) and gets its own token. They live in the shell for the seeding run and
   nowhere else; delete the Seeder app once the store is built.
3. From the repo, with `SHOPIFY_SHOP=<store>.myshopify.com` and `SHOPIFY_ADMIN_TOKEN=shpat_…`:

   ```
   .venv/bin/python scripts/seed_dev_store.py --products
   .venv/bin/python scripts/seed_dev_store.py --mix "A1:40,A:80,B:280,none:1100" --heroes scripts/demo_heroes.json --dry-run
   .venv/bin/python scripts/seed_dev_store.py --mix "A1:40,A:80,B:280,none:1100" --heroes scripts/demo_heroes.json
   ```

   The first call builds the catalogue (twelve products, images served from haliascore.com). The
   dry run prints the first clients and the date span. The full run takes about an hour at
   Shopify's pace and can be stopped and restarted: clients already in the store are skipped.
   `--wipe` removes everything tagged halia-sample, orders first.
4. Install HALIA on the store from the Partner Dashboard app page ("Select store"). This is the
   managed install a reviewer goes through, so it doubles as the dry run of the install path.
5. Console → comped clients → add the store's myshopify domain. The console list replaces the
   environment list once saved, so the environment alone does not comp a store.
6. Open the app once. The book scores in one to two minutes and stays warm while the store is
   in use; after a server restart it is scored again in the background within a few minutes.

## The five clients to click

| Client | Grade | Story |
|---|---|---|
| Lady Ottoline Ferrers-Vane | A* | £1,900 spent. Lives at One Hyde Park, buys through a private office, her assistant places the orders. The engine's case for her is the evidence panel. |
| Imogen Castellane | A | £3,200 over three orders, last one fourteen months ago. A banker's work email. The gone-quiet play. |
| Rafael Okonkwo-Hale | B | One order, six days ago, paid mailbox. The fresh play: follow up while it is warm. |
| Celeste Marchetti | proven | £38,400 over nine orders. The engine agrees she is a VIC; she is not hidden, she is the benchmark. |
| Theo Lindqvist | B | £420, one order, one mild signal. What a modest flag looks like, so the top grades mean something. |

Search by surname in the dashboard or the toolbar.

## Before the call

- No deploys from the day before. A deploy restarts the server and the book is re-scored in the
  background; it is back within ten minutes, but not during a demo.
- Fifteen minutes before: open the demo store's app so the book is warm. Clear the "Last shopped"
  filter at the top. Open the store admin in a second tab with the toolbar signed in. Have
  `output/mvp.html` open locally as a fallback if Shopify is down.
- Close other tabs, notifications off, 125% zoom.

## The twelve minutes

1. Overview: the whole book scored, the potential VICs counted, latent value. One sentence on
   what a potential VIC is: a client whose history says they could spend far more here.
2. Grade mix, then the A* list. Open Lady Ferrers-Vane: the evidence, in plain facts.
3. Plays → Gone quiet. Open Imogen Castellane. Mark as contacted from the drawer; show the note
   land in the pipeline.
4. Campaigns: one existing campaign and what it tracks.
5. Switch to the admin tab: the toolbar on a customer page, one person, one next move. Draft a
   message.
6. Sell: a private selection for Rafael, the catalogue link.
7. Settings: what Halia holds and for how long. Scores live in memory while the store is in use
   and are released within an hour of the last use; nothing is written to disk.

## Lines

- Capacity is inferred from the merchant's own data. Halia never knows what a client spends
  elsewhere, and never says so.
- Maison Aurelle is fictional. Say it before anyone asks.
- Their trial runs on their own store through a bridge app, with their own data, and nothing
  leaves their Shopify. Scores are not stored; their customers are not copied anywhere.
- Signals that would single people out by origin stay off by default; the reasons shown are
  facts about the account, not inferences about the person.
