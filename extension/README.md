# Halia browser extension

A persistent clienteling toolbar that lives where your team already works: the store admin
(Shopify, BigCommerce, WooCommerce), WhatsApp Web, and Gmail. It keeps your templates, running
campaigns and catalogue one click away, and its top "client" section updates live as you move
between conversations. It reads the client shown on the page, asks your Halia account, and stores
nothing about the customer, in keeping with Halia's zero-retention model.

## The toolbar

A handle sits on the right edge of the page; click it to open the panel (it remembers open or
closed). The panel has four always-ready sections:

- **Client** — updates as you open a chat, email or customer: grade (A\*, A, B…), hidden-VIC or
  gone-quiet flag, latent value, recent order recency, an open-basket alert with a link, the
  reasons they scored, the recommended next move, and links to open them in Halia or your store.
- **Templates** — your outreach templates, filled with the active client's name. **Insert** drops
  one straight into the WhatsApp/Gmail reply box, or copy it.
- **Campaigns** — the campaigns running now, each with a one-click **tagged catalogue link**
  (carrying the campaign's UTM for the current channel) to insert or copy, plus copy-UTM.
- **Catalogue** — your live catalogue link, ready to insert or copy.

When no client is on screen the toolbar still shows templates, campaigns and catalogue, so it is
always useful.

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
