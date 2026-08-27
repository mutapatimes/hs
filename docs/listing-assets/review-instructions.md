# App Store review: fixes and submission notes (ref 129143)

What Shopify flagged on 2026-08-27, what changed in code, and what to enter in the Partner
Dashboard when resubmitting.

## 1.2.1 Billing must be on-platform

**In the app**: every Shopify tenant already subscribes through the Shopify Billing API
(`appSubscriptionCreate` → Shopify's approval page → back into the app). Stripe is only used for
tenants on other platforms and for custom-distribution bridge apps, which Shopify bars from the
Billing API. Nothing in the public app sends a merchant off-platform to pay.

**In the listing (the actual complaint)**: the listing's Pricing section declared one plan while
the app offers four. Enter all of them in Partner Dashboard → App listing → Pricing, and make
sure the "custom pricing" option is on:

| Plan | Type | Price | Note for the listing |
|---|---|---|---|
| Free scan | Free | £0 | Connect and see how many VICs are hiding. Always free. |
| Discovery | Recurring, every 30 days | £150 | Up to 15k customers, 3 seats |
| Signal | Recurring, every 30 days | £500 | 15k–75k customers, 5 seats |
| Atelier | Recurring, every 30 days | £1,200 | 75k+ customers, 10 seats |
| Maison | Custom pricing | contact us | Groups and largest houses; arranged with the merchant |

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
choose a plan, approve the Shopify test charge, land back in the app**, then the Maison
custom-plan path ("Talk to us"). English voiceover; keep it under 8 minutes.

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
> Billing: Settings → Billing lists every plan. Choosing Discovery, Signal or Atelier opens
> Shopify's subscription approval page (test mode: no charge). Maison is custom pricing and
> shows "Talk to us". Switching to Free cancels the subscription through Shopify.
>
> Optional hosted dashboard (outside Shopify): sign in with a magic link at
> https://haliascore.com/app using the email below. [add a review mailbox you control]

Keep the mailbox live for the whole review window and check it daily.
