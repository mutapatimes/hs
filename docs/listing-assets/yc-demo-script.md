# YC demo video: the first-order story on Maison Aurelle

A Loom screen recording, about 85 seconds, on the Maison Aurelle development store. One client
carries the whole story: Nina Halloran, a new customer with a single £100 order. To the eye she is
nothing special: an ordinary-looking email, a village address in Wiltshire. The engine grades her
A* on facts nobody would notice by eye:

- the house is a named property ("The Old Rectory")
- the postcode is a high-value area in the Land Registry data
- her email is on her own domain
- the number is a landline
- the delivery line is marked for the housekeeper

No work email, no prime London postcode: nothing an associate would spot unaided. That is the
point of the demo.

## Setting up the client

```
SHOPIFY_SHOP=<store>.myshopify.com SHOPIFY_CLIENT_ID=… SHOPIFY_CLIENT_SECRET=… \
  .venv/bin/python scripts/seed_dev_store.py --heroes scripts/demo_hero_first_order.json --limit 0
```

`hours_ago` in the hero file timestamps the order, so it sits at the top of the Orders page as
"just placed". A client already in the store is skipped, so to place a fresh order on a later day
change the name and email in the file (or remove her first: orders, then the customer).

Then open the Halia app once so the book is re-scored with her in it. Search "Halloran" under
Clients to confirm the grade before recording.

## Before and after on the same page

The "before" shot is the Shopify customer page with nothing from Halia on it; the "after" is the
same page with the toolbar showing the grade and the reasons. Two ways to get the "before":

- Toggle the Chrome extension off (chrome://extensions) for the first half, pause Loom, toggle it
  on, reload the page, resume.
- Or keep the extension off entirely and, for the "after", switch to the Halia app: Clients, search
  "Halloran", open the drawer. The grade, the reasons and Draft with Halia are all there.

Keep "Keep tags in sync automatically" (Settings, Shopify) off before recording, so her profile
shows no Halia tag in the "before" shot. Tagging her from the Clients list ("Tag in Shopify")
after the before-shot is an optional extra: the profile then carries `Halia:A*` and `Halia:Fresh`
on the Shopify page itself.

## The shots

| Time | Screen | Words |
|---|---|---|
| 0:00 | The Shopify admin with Halia open (Apps, Halia, Overview) | Halia plugs into the systems a brand already runs. For this demo I'll show its core value: spotting potential VIPs from their very first order. |
| 0:10 | Shopify admin, Orders. Top row: Nina Halloran, £100.00 | Imagine this is Dior's Shopify admin. A new customer has just placed a one hundred pound order. |
| 0:17 | Click the customer. One order, a village address, a plain email, no tags, no notes | There's no purchase history, and nothing here stands out: an ordinary email, a village in Wiltshire. Nothing would flag her for VIP attention. Without a timely, personal follow-up, Dior may never build a relationship with her, and she may never come back. |
| 0:35 | The same customer with Halia on. The grade, then read the reasons off the screen | With Halia, the same customer now carries a score, and the reasons behind it. None of them are obvious on their own. Her email is on her own domain. The house is a named property, in a postcode where homes sell at the top of the market. The number is a landline, and the order is marked for the housekeeper. Small facts. Together, they say potential VIP, and the sales team can prioritise a personal follow-up straight away. |
| 1:02 | Draft with Halia. The note appears | Halia even drafts the first note, in the brand's own voice. |
| 1:07 | Halia Clients list, the potential VIPs counted | As little as one percent of customers can account for up to half of revenue, so spotting them early matters. Halia finds potential VIPs before their spending history makes it obvious. |

The teleprompter version of this script carries the screen cue above each block.

## Recording

- Loom: screen and camera bubble, 1080p, the browser window only. Notifications off, 125% zoom,
  one tab for the admin and one for the app.
- No deploys from the day before: a deploy restarts the server and the book is re-scored in the
  background for ten minutes.
- Say the £100 as "one hundred pounds". Read the reasons off the screen rather than from memory;
  they are facts about the account, not inferences about the person. No money figure is shown for
  the home, by design: say "a high-value area", never a price.
- "Dior" is the hypothetical in the script; the store on screen says Maison Aurelle, which is
  fictional. Nobody in it exists.
