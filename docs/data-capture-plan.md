# In-store data capture through the iOS app

Planning notes (2026-08-25). The problem, from the founder's own shop-floor experience: luxury
retail data capture is broken. Most sales are in-store, associates rarely capture the client, and
what is captured lands on paper or in a till field nobody reads. The iOS app is already in the
associate's pocket; it can become the capture device, and every capture lands in Shopify as a
customer profile and is scored by Halia the moment it is saved.

## The design principle: the store captures, Halia processes

The client hands their details to the store, not to Halia. That is also the legal truth: the
merchant is the data controller, Halia is a zero-retention processor, and the data's destination
is the merchant's own Shopify. So the capture UI is **store-branded** (the shop's name, the
shop's privacy policy), and Halia's name does not need to appear at the point of capture, the same
way no signup form lists its processors. This satisfies the founder's requirement that a client
handed the phone does not see a "client intelligence platform", without deceiving anyone: the
form says exactly who is collecting (the store) and why (to look after you as a client).

What we do NOT do: collect anything the form does not show, or bury marketing consent inside a
generic save. Opt-in is explicit and unchecked by default.

## Surface 1: the handover screen (host app)

"Add client" in the iOS app opens a screen styled like the native iOS add-contact UI: circular
photo placeholder, grouped inset fields, Cancel/Done nav bar. Fields: name, phone, email,
birthday, plus retail fields tucked below the fold: sizes, preferences, occasion dates, notes.

- **Handover mode**: entering the screen locks the rest of the app; Done or Cancel returns to a
  neutral confirmation, and getting back to the desk requires the associate (their seat session).
  The client can never swipe into grades or the client book.
- A store-branded header ("Save your details with <Store name>") and a consent line above Done:
  "<Store> will keep these details to look after you as a client" + privacy policy link, plus an
  unchecked marketing opt-in (email / SMS / WhatsApp, granular).
- On Done: the profile posts to the backend, and the associate (after handover ends, never
  during) sees the grade the new client scored.

## Surface 2: QR self-capture (best consent posture, zero handover)

The app (and the dashboard) can show a QR that opens a store-branded capture form on the
client's own phone; a printable version sits by the till or at events. Same backend, same
pipeline. This variant has the cleanest consent story (the client acts on their own device) and
no handover risk at all. NFC tag on the counter can point at the same URL.

## Surface 3: capture from where associates already talk

- **Keyboard**: a Save-client key parses a name/number/email from the chat the associate is in
  (WhatsApp, iMessage) and creates the profile without leaving the conversation.
- **Share extension**: share an iOS contact card (vCard) into Halia → client book.
- **Business-card / note scan**: VisionKit OCR prefills the handover form from a card or a
  handwritten note.
- **CallKit**: after a call with an unknown number, a local prompt: "Add caller to the client
  book?" (VIP caller-ID infrastructure already exists.)
- **POS tile** (parked manifest): when revived, the natural at-till capture point.

## The pipeline (shared by every surface)

`POST /v1/capture` (seat-authed, so every capture is attributed to the associate):

1. **Dedupe** against Shopify customers by email/phone: update, never duplicate.
2. **Write** the Shopify customer: fields, plus metafields (`halia.*`) for sizes, preferences,
   occasions; tag `halia-captured` (+ an event tag when captured at a trunk show etc.).
3. **Consent record** in metafields: consent text version, timestamp, channel (handover / QR /
   keyboard / scan), associate seat, store location. Marketing opt-ins are written to Shopify's
   native email/SMS marketing-consent fields so Klaviyo and every downstream tool respect them.
4. **Score immediately**; return the grade to the associate surface once the client-facing moment
   is over. Zero retention on Halia's side: the profile lives in the merchant's Shopify only.

## Compliance guardrails

- Controller = merchant; processor = Halia (existing DPA/DPIA docs cover this; capture adds a
  consent-collection record, which strengthens the merchant's lawful basis rather than weakening it).
- Marketing opt-in: explicit, granular, unchecked by default, revocable through the store as usual.
- Data minimisation: only what the form shows; no hidden fields, no device-contacts import of
  third parties.
- Optional double opt-in (confirmation email) toggle for stricter markets.

## Why this sells (GTM note)

"Data capture that scores itself" is a wedge into exactly the demographic where most sales are
in-store and databases are thin — including the small 70% of the market (see
docs/unit-economics.md). Every capture makes the merchant's Halia scan better, which makes the
subscription stickier: capture feeds scoring feeds clienteling feeds retention. It is also a
demoable moment: hand over the phone, type a name, watch a graded profile appear in Shopify.

## Build order

1. **Phase 1**: `POST /v1/capture` + the handover screen in the host app (store-branded,
   handover-locked, consent line, marketing opt-in, instant Shopify write + score).
2. **Phase 2**: QR self-capture page (tenant-branded, printable QR from the dashboard).
3. **Phase 3**: keyboard Save-client key, share-extension vCard intake, card scan.
4. **Phase 4**: CallKit add-caller prompt; POS tile when revived.
