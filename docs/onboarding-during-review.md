# Onboarding Shopify clients while the app is under review

Shopify is reviewing Halia's public app. Until it approves, a store outside your own Partner
organisation cannot install the public app: Shopify blocks it with "This app is under review."
Two paths work today. Both end with the client fully live on Halia.

| | Bridge app (Path A) | Request form (Path B) |
|---|---|---|
| Who starts it | You, for a brand you are courting | The brand, arriving at /connect on their own |
| Client experience | One click, like a normal app install | Store + email, then your one-click link within a day |
| Your part | ~5 minutes in the Partner Dashboard | The same 5 minutes, when their request lands |
| Billing | Stripe | Stripe |

After approval, one env flip restores the normal public one-click for everyone new.

---

## Path A: bridge app (one-click, you set it up first)

A "bridge app" is a private copy of Halia you create in your Partner Dashboard for one specific
store. Shopify does not review these, so the client can install it today. It points at the same
backend as everything else.

### You do (once per client, ~5 minutes)

1. Go to **partners.shopify.com → Apps → Create app**. Name it "Halia - {Brand}".
   The name is only visible to you. Ignore any "Start using Shopify CLI" banner: the browser
   form is all you need.
2. On the app's settings screen, fill the fields exactly like this (they mirror the public app):

   | Field | Value |
   |---|---|
   | App URL | `https://haliascore.com` (replace the example.com placeholder) |
   | Embed app in Shopify admin | On |
   | Preferences URL | Leave empty |
   | Webhooks API version | Leave the offered default |
   | Scopes | `read_customers,read_orders,read_all_orders,write_customers,read_products` |
   | Optional scopes | Leave empty |
   | Use legacy install flow | Off |
   | Allowed redirection URL(s) | `https://haliascore.com/connect/shopify/callback, https://haliascore.com` |
   | POS | Skip |
   | App proxy (optional) | URL `https://haliascore.com/proxy/catalogue`, prefix `a`, subpath `catalogue`. Makes catalogue links live on the client's own domain. |

   **If `read_all_orders` is flagged "requires permission"**: click **Request access** (it reads
   order history older than 60 days, for the merchant's own clienteling; Halia retains nothing).
   If the form will not save with it, remove it for now, save, and add it back once granted;
   until then Halia scores the most recent 60 days.
3. Save, and release the version if the dashboard asks.
4. Under **Distribution**, choose **Custom distribution** and enter the client's
   `.myshopify.com` address. Never do this on the main Halia app: the distribution choice is
   permanent per app.
5. From the app's overview page, copy the **Client ID** and **Client secret** (two codes Shopify
   shows you). Add them to the `HALIA_SHOPIFY_CUSTOM_APPS` env var on Render:

   ```
   HALIA_SHOPIFY_CUSTOM_APPS=brand.myshopify.com=CLIENT_ID:CLIENT_SECRET
   ```

   More clients later are appended with commas:

   ```
   HALIA_SHOPIFY_CUSTOM_APPS=brand-a.myshopify.com=id:secret,brand-b.myshopify.com=id:secret
   ```

   Redeploy so it takes effect.
6. Send the client either the install link (Distribution → **Generate link**) or simply
   `https://haliascore.com/connect`. The wizard recognises their store and shows them the
   one-click card.

### The client does

1. Click the link.
2. Approve the permissions screen in their Shopify admin. Done: Halia appears in their admin
   and the dashboard loads with their scores.

### First-install checks (do these on client number one)

- Open their dashboard and confirm order history goes back further than 60 days. If it stops
  at ~2 months, Shopify did not grant `read_all_orders` to the bridge app; tell me and we
  adjust the scope request.
- Confirm the Stripe billing panel renders in their Settings (requires the Stripe env vars
  below).

---

## Path B: the request form (brands that arrive on their own)

The /connect wizard offers no self-serve Shopify setup during review. A brand that shows up
picks Shopify, enters their store address and email, and taps **Request access**. That emails
hello@haliascore.com with their address as Reply-To (or, if no mail provider is configured on
Render yet, hands them a prefilled mailto button reaching the same inbox).

When a request lands: follow Path A for their store and reply with the install link.

---

## Billing during review (both paths)

Every review-window client is a bridge-app client, and custom-distribution apps are not
allowed to use Shopify's billing, so they all pay through **Stripe**. The code is live; it
needs three env vars on Render before anyone can pay:

| Env var | What it is |
|---|---|
| `STRIPE_SECRET_KEY` | Your Stripe API key. Alone, this is enough: plan cards open real Stripe Checkout |
| `STRIPE_PLAN_LINKS` | `discovery=https://buy.stripe.com/...,signal=...,atelier=...` payment links, one per plan, created in Stripe |
| `STRIPE_WEBHOOK_SECRET` | From a Stripe webhook endpoint pointed at `https://haliascore.com/webhooks/stripe` |

The client sees plan cards in their dashboard; choosing one opens Stripe checkout; the webhook
marks them active automatically. They manage or cancel from the Stripe portal in Settings.

Without the webhook secret, activation still lands when the merchant returns to the dashboard after paying.

---

## After Shopify approves the public app

1. Set `HALIA_SHOPIFY_APP_LIVE=1` on Render and redeploy. The `/connect` wizard now shows the
   one-click Shopify card to **every** store, wired to the public app. That is the whole
   revert for new clients.
2. **Leave existing bridge clients exactly as they are.** Their apps keep working
   indefinitely, their Stripe billing keeps working, and nothing forces a migration. Keep
   their entries in `HALIA_SHOPIFY_CUSTOM_APPS`.
3. Migrate a bridge client to the public app only if you want them on Shopify billing. To do
   it: they install the public app from the App Store listing (one click), Halia swaps to the
   public app's token for their store automatically on install, then cancel their Stripe
   subscription and have them subscribe on the Plans screen. Remove their env entry only
   after that install has succeeded.

---

## Env var quick reference

| Var | Purpose |
|---|---|
| `HALIA_SHOPIFY_APP_LIVE` | `1` once Shopify approves; shows the public one-click to everyone |
| `HALIA_SHOPIFY_CUSTOM_APPS` | `shop=client_id:secret,...` one entry per bridge client |
| `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` | The public Halia app's credentials |
| `STRIPE_SECRET_KEY`, `STRIPE_PLAN_LINKS`, `STRIPE_WEBHOOK_SECRET` | Stripe billing for bridge clients |
| `HALIA_SIGNUP_CODE` | Optional gate on `/connect`; share it with invited clients |
