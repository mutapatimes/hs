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
  gone-quiet flag, a **"contacted 2d ago by Sarah"** warning if a colleague already reached out
  (read from the shared log, so you don't double-message), latent value, recent order recency, an
  open-basket alert with a link, the
  reasons they scored, the recommended next move, **Add to pipeline** (Shopify write-back stores),
  a **Note** field to jot context (saved to the customer in your Shopify, shown in the dashboard
  pipeline), and links to open them in Halia or your store.
- **The brief** — at the top of the Templates section, and the fastest way to act. Press **Read this
  conversation** and Halia returns three things at once:
  1. **Where the relationship stands** — two lines on who this is and what they want right now, read
     from the live conversation plus their standing in your book.
  2. **The next moves** — up to four recommended actions, each with a reason. The ones Halia can
     carry out are buttons: add to your outreach list, add to the campaign running now, log that you
     contacted them, drop in the catalogue. The rest are shown as advice.
  3. **A reply, ready to send** — written for this person and this conversation, in a register that
     matches their standing. **Insert** drops it into the reply box, or copy it. Add a line of intent
     ("confirm the exchange", "invite to the trunk show") and press **Read again** to steer it.

  It always returns something. With no AI key configured, once a shop's weekly cap is reached, or on
  any model failure, the summary comes from your scored book, the actions from the client's own
  standing, and the reply from your best-matching template. Zero-retention holds: the standing and
  the thread are read live and used in-flight, never stored.
- **Templates** — your outreach templates, filled with the active client's name. **Insert** drops
  one straight into the WhatsApp/Gmail reply box, or copy it.
- **Campaigns** — the campaigns running now. With a client on screen, **Add this client** drops them
  into the campaign; each also offers a one-click **tagged catalogue link** (carrying the campaign's
  UTM for the current channel) to insert or copy, plus copy-UTM.
- **Build a cart** (Shopify) — search your products, add variants to a cart for the client, then
  **Send cart**: it builds a Shopify cart permalink (`/cart/{variant}:{qty},…`) that pre-loads their
  basket, dropped straight into the reply or copied. If a campaign is running, the link is tagged
  with its UTM so the purchase attributes.
- **Catalogue** — your live catalogue link, ready to insert or copy.

### Inbox triage dots (Gmail + WhatsApp)

In the Gmail inbox list, each conversation from a known client gets a small grade tag (A\*, A, B…)
before the sender's name, coloured by grade, so the highest-grade client is answered first. Grades
are looked up in one batched request per new set of visible senders and match against your book;
non-clients get no tag. The **WhatsApp chat list** gets the same dots, matched on the saved contact
name (WhatsApp exposes no address there), so naming your Shopify customers the same as your WhatsApp
contacts gives the best match.

One-click actions preserve zero-retention: "Add to pipeline" writes a stage tag + metafield into
your own Shopify; "Add this client" stores only the opaque customer id in the campaign, exactly as
the dashboard does. No customer data is stored by Halia.

When no client is on screen the toolbar still shows templates, campaigns and catalogue, so it is
always useful.

### Clienteling mode vs Internal (team) mode

A toggle in the toolbar header switches between two modes, so the whole team stays in the loop and
nobody double-messages a client:

- **Clienteling** (default on WhatsApp/Gmail/admin): the client-facing sections above.
- **Internal** (default on Slack): a **Team** section instead — log that you contacted the current
  client (with a reason), which records to the shared pipeline and broadcasts to your team's Slack
  if connected; premade team messages to paste into a channel; and a to-do list built from your
  book (new orders from top clients to acknowledge, proven clients gone quiet to win back). Set your
  name in the extension options so team logs are attributed to you.

On Slack the toolbar opens in Internal mode automatically and inserts team messages into the
composer. Zero-retention holds: contact logs are written to your own Shopify and/or posted to your
own Slack; Halia stores nothing about the customer.

## Ambient surfaces and the radar

The toolbar also runs on **Instagram DMs** (`instagram.com`, matched by the conversation name) and
**Google Calendar** (`calendar.google.com`), where opening an event surfaces the guest's brief so
you walk into an appointment knowing exactly who they are (matched by the guest's email).

It also appears in the **helpdesk and marketing tools your team already uses**, so support and
marketing see who quietly matters:

- **Gorgias** and **Zendesk** — on an open ticket, the requester is recognised by email, so support
  knows if it is an A\* client and can reply in the right register (and insert a template).
- **Klaviyo** — on a customer profile, their Halia grade appears (read-only), so a marketer sees who
  matters while building flows and segments.
- **Microsoft Teams** — a second internal surface (like Slack): the toolbar opens in Internal mode
  with team to-dos and premade messages, inserted into the Teams composer.

Identity matching on each of these is best-effort against the tool's own markup (mostly by email);
if a surface comes up empty, the selectors just need tuning for that tool's current UI.

**The brief reads the conversation on every surface that has one**: WhatsApp Web, Gmail, Instagram
DMs, Gorgias and Zendesk. On a helpdesk that means the brief answers the actual complaint, not just
the client's grade. Where there is no conversation to read (Klaviyo, a customer page in the store
admin) the button still works and briefs from the client's standing alone.

**Right-click anywhere** — select an email, phone number or name on any page and choose
**"Look up … in Halia"**; a desktop notification returns their grade, latent value and next move.
Works on sites the toolbar doesn't run on.

**Proactive VIC radar** — with order alerts set up in Halia, the extension fires a quiet desktop
notification the moment a high-grade client places an order, wherever you are in the browser.
Toggle it in the extension options. It reads the same live alert feed the dashboard uses and stores
nothing; the first check is silent so installing never blasts a backlog.

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
