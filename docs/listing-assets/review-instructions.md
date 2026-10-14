# App Store review: fixes and submission notes (ref 129143)

What Shopify flagged on 2026-08-27, what changed in code, and what to enter in the Partner
Dashboard when resubmitting.

## 1.2.1 Billing must be on-platform

**In the app**: every Shopify tenant already subscribes through the Shopify Billing API
(`appSubscriptionCreate` → Shopify's approval page → back into the app). Stripe is only used for
tenants on other platforms and for custom-distribution bridge apps, which Shopify bars from the
Billing API. Nothing in the public app sends a merchant off-platform to pay.

**In the listing (the actual complaint)**: the listing's Pricing section declared one plan while
the app offers four. Enter all of them in Partner Dashboard → App listing → Pricing. Do not
list a custom-priced plan (see the 2026-10-14 round below):

| Plan | Type | Price | Note for the listing |
|---|---|---|---|
| Free scan | Free | £0 | Connect and see how many VICs are hiding. Always free. |
| Discovery | Recurring, every 30 days | £150 | Up to 15k customers, 3 seats |
| Signal | Recurring, every 30 days | £500 | 15k–75k customers, 5 seats |
| Atelier | Recurring, every 30 days | £1,200 | 75k+ customers, 10 seats |

Currency GBP. Seats beyond the bundle are £15 each per 30 days (mention in the plan notes).
Prices in the listing must match `halia/plans.py` exactly; that file is the single source.

**Test charges**: `HALIA_SHOPIFY_BILLING_TEST=true` stays on until the listing is approved, so
the reviewer's plan choice creates a test subscription (nothing is charged). Flip it to `false`
on launch day.

## 2.1.1 The 502 after install

Cause: the embedded entry ran the entire first fetch + scoring inside the install navigation.
On a cold Render instance a large book outlasts the proxy timeout → 502.

Fixed (2026-08-27): first load now exchanges the token, starts scoring in the background, and
renders a "Scoring your customers" screen that polls `/v1/sync/state` and reloads itself when
the book is ready. The install navigation returns in well under a second.

**Still to do on Render (you)**: move the web service off the free plan before resubmitting.
Free instances sleep after idle and take 30–50 s to wake, which the reviewer experiences as a
blank wait or a 502 before our code even runs. Starter is enough.

## 4.5.3 Demo screencast

Re-record from `screencast-script.md` (updated). It now walks install → scoring screen →
Overview → Clients → a client and the message templates → Settings (alerts, team) → **Billing:
choose a plan, approve the Shopify test charge, land back in the app**, switch plan, then
switch to Free. English voiceover; keep it under 8 minutes.

## 4.5.4 / 4.5.5 Test credentials

Paste into "Testing instructions" in the Partner Dashboard:

> Halia has no separate login. Install the app on your development store; it opens embedded
> in the Shopify admin and authenticates with the Shopify session. On first open you will see
> "Scoring your customers" for a few seconds while the store's order history is read and
> graded; the dashboard then loads on its own.
>
> To test features you need a store with customers and orders (any dev store with sample data
> works; the more orders, the more the app surfaces). Grades appear on Clients; open any client
> for the reasons, templates and the message drawer. Settings → Alerts turns on order alerts;
> Settings → Team creates seats for the iPhone app and Chrome extension (optional).
>
> Billing: Settings → Billing lists every plan: Free scan, Discovery, Signal and Atelier.
> Choosing a paid plan opens Shopify's subscription approval page (test mode: no charge) and
> returns you to Halia on that plan. From a paid plan, "Switch to" another plan replaces it
> immediately through the same approval page, and "Switch to Free" cancels the subscription
> through Shopify. All charges appear under Settings → Billing in your Shopify admin.
>
> Optional hosted dashboard (outside Shopify): sign in with a magic link at
> https://haliascore.com/app using the email below. [add a review mailbox you control]

Keep the mailbox live for the whole review window and check it daily.


---

# Round of 2026-10-14

## 1.2.3 Allow pricing plan changes

**Flagged**: the custom plan (Maison) could not be upgraded to through Shopify's approval page,
and the reviewer could not downgrade back to Free.

**Fixed in code**:
- The Shopify plan list now shows only plans a merchant can take through Shopify: Free scan,
  Discovery, Signal, Atelier. Maison is no longer a card for Shopify merchants
  (`billing_shopify.shopify_catalogue`).
- Plan switches are created with `replacementBehavior: APPLY_IMMEDIATELY`, so moving between paid
  plans replaces the old charge at once, up or down.
- "Switch to Free" cancels every active Halia subscription on the store, then asks Shopify again
  and only reports Free once none is left. If Shopify cannot be reached it says so instead of
  claiming success.
- A live plan the app does not recognise still counts as paid, so the Free button never
  disappears.
- Shopify merchants are never sent to Stripe; every upgrade prompt opens Settings → Billing.

**You, in the Partner Dashboard**: App listing → Pricing → remove the Maison / custom plan and
turn the custom-pricing option off, so the listing shows exactly the four plans the app offers.

## 2.1.4 The 400 error on setup

**Cause**: on first open the app swaps Shopify's one-minute sign-in token for a store token. A
token a few seconds past its life is refused by Shopify with HTTP 400, and the app printed that
400 on a "Couldn't load your scores" page. Reloads (the Refresh button, Re-score, saving
settings) reused the old token in the address and could land on the same page.

**Fixed in code**:
- A refused exchange now fetches a fresh sign-in from App Bridge and comes straight back; the
  merchant sees "Opening Halia…" for a moment instead of an error.
- Every reload inside the admin goes through App Bridge for a fresh sign-in first.
- The retry is guarded by a timestamp, so a genuine fault shows its reason once rather than
  looping.
- Scoring failures read as a sentence ("Shopify has not given Halia access to customer details
  on this store yet…"), never raw Shopify JSON.

**You, before resubmitting**: in the Partner Dashboard, confirm Protected customer data access
(name, email, phone, address) is submitted for the public Halia app, or a reviewer's store
cannot read customer details at all.

## 4.5.3 Screencast

Re-record from `screencast-script.md` (rewritten): a full walk from install to plan changes,
with a caption naming each step.
