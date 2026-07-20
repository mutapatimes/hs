# Halia browser extension

Puts a client's Halia grade, the reasons behind it, and the next move right where your team
already works: the store admin (Shopify, BigCommerce, WooCommerce), WhatsApp Web, and Gmail. The
extension reads the client shown on the page, asks your Halia account for their grade, and renders
a small card in the corner. It stores nothing about the customer, in keeping with Halia's
zero-retention model.

## What it shows

On a customer/order in your store admin, an open chat in WhatsApp Web, or an open email in Gmail:

- the grade (A\*, A, B…) and whether they are a hidden VIC or a proven client gone quiet
- their latent value, recent order recency, and why they scored (the signals)
- an open-basket flag when they have an abandoned checkout, with a link to it
- the recommended next move
- your own outreach templates: **insert one straight into the reply box** on WhatsApp Web and
  Gmail, or copy it
- a link to open them in Halia or in your store, and to copy your catalogue link

## Install (unpacked, for now)

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and choose this `extension/` folder.
3. Click the Halia icon → **Open settings**.
4. In Halia, go to **Settings → Integrations → Browser extension**, generate a token (it is shown
   once), and paste it into the extension's settings. Leave the address as `https://haliascore.com`
   unless your team uses a different Halia URL.
5. Press **Test connection**. You should see "Connected".

## Surfaces and how identity is read

| Surface | Where it runs | How the client is matched |
| --- | --- | --- |
| Shopify admin | `admin.shopify.com`, `*.myshopify.com/admin` | customer id in the URL; email on order pages |
| BigCommerce | `*.mybigcommerce.com/manage` | customer id in the URL; email on order pages |
| WooCommerce | your own domain's `wp-admin` (added in settings) | billing/customer email field |
| WhatsApp Web | `web.whatsapp.com` | the chat's phone number, else an exact name match |
| Gmail | `mail.google.com` | the other correspondent's email address |

WhatsApp and Gmail match against the customers already in your Halia book. If the person isn't a
flagged client, the card says so.

### WooCommerce

WooCommerce admin lives on your own domain, which isn't known ahead of time. In the extension's
settings, add your store address under **WooCommerce store**. Chrome asks you to grant access to
that one site, and the badge then runs inside its `wp-admin`. Remove it any time.

## Privacy and permissions

- The token lives only in the extension's synced storage and in the service worker at request time.
  Page scripts never see it.
- All API calls go from the extension (which holds host access to your Halia URL) to
  `POST /v1/extension/lookup`. Halia reads its in-memory scored book and returns one client's
  grade. Nothing about the customer is written down, by the extension or by Halia.
- The base host permissions are limited to your Halia URL. Access to Shopify/BigCommerce admin,
  WhatsApp Web and Gmail is scoped to those specific sites. WooCommerce access is requested only
  for the store you add.

## Development

- Point the extension at a local server by setting the address to `http://localhost:8000` in
  settings (localhost is in the manifest's host permissions).
- After editing files, hit the reload icon on the extension card in `chrome://extensions`.
- The token is minted by `POST /v1/extension/token` and validated by hashing the header
  `X-Halia-Ext-Token` against `extension_tokens` (see `halia/api/extension.py`).

## Not yet wired

One-click "add to campaign" and "add to pipeline" from the card are planned, and would POST
through the same extension token. Grade dots on the WhatsApp/Gmail thread list (so an associate
answers the highest-grade client first) are the other fast-follow.
