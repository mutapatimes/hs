# YC demo video: the first-order story on Maison Aurelle

A Loom screen recording, about 70 seconds, on the Maison Aurelle development store. One client
carries the whole story: Henry Ashcombe, a new customer with a single £100 order, graded A* by the
engine on the account's facts alone (a Goldman Sachs work email, a Knightsbridge address, an
ultra-prime area).

## Setting up the client

```
SHOPIFY_SHOP=<store>.myshopify.com SHOPIFY_CLIENT_ID=… SHOPIFY_CLIENT_SECRET=… \
  .venv/bin/python scripts/seed_dev_store.py --heroes scripts/demo_hero_first_order.json --limit 0
```

`hours_ago` in the hero file timestamps the order, so it sits at the top of the Orders page as
"just placed". A client already in the store is skipped, so to place a fresh order on a later day
change the name and email in the file (or wipe and re-seed him).

Then open the Halia app once so the book is re-scored with him in it. Search "Ashcombe" under
Clients to confirm the grade before recording.

## Before and after on the same page

The "before" shot is the Shopify customer page with nothing from Halia on it; the "after" is the
same page with the toolbar showing the grade and the reasons. Two ways to get the "before":

- Toggle the Chrome extension off (chrome://extensions) for the first half, pause Loom, toggle it
  on, reload the page, resume.
- Or keep the extension off entirely and, for the "after", switch to the Halia app: Clients, search
  "Ashcombe", open the drawer. The grade, the reasons and Draft with Halia are all there.

Keep "Keep tags in sync automatically" (Settings, Shopify) off before recording, so his profile
shows no Halia tag in the "before" shot. Tagging him from the Clients list ("Tag in Shopify")
after the before-shot is an optional extra: the profile then carries `Halia:A*` and `Halia:Fresh`
on the Shopify page itself.

## The shots

| Time | Screen | Words |
|---|---|---|
| 0:00 | The Shopify admin with Halia open (Apps, Halia, Overview) | Halia plugs into the systems a brand already runs. For this demo I'll show its core value: spotting potential VIPs from their very first order. |
| 0:10 | Shopify admin, Orders. Top row: Henry Ashcombe, £100.00 | Imagine this is Dior's Shopify admin. A new customer has just placed a one hundred pound order. |
| 0:17 | Click the customer. One order, customer since today, no tags, no notes | In a traditional setup there's no purchase history, nothing to flag them for VIP attention. Without a timely, personal follow-up, Dior may never build a relationship with them, and they may never come back. |
| 0:32 | The same customer with Halia on. The grade, then the reasons | With Halia, the same customer now carries a score, and the reasons behind it: a work email at a major bank, a Knightsbridge address. The sales team can prioritise a personal follow-up straight away. |
| 0:47 | Draft with Halia. The note appears | Halia even drafts the first note, in the brand's own voice. |
| 0:52 | Halia Clients list, the potential VIPs counted | As little as one percent of customers can account for up to half of revenue, so spotting them early matters. Halia finds potential VIPs before their spending history makes it obvious. |

The teleprompter version of this script carries the screen cue above each block.

## Recording

- Loom: screen and camera bubble, 1080p, the browser window only. Notifications off, 125% zoom,
  one tab for the admin and one for the app.
- No deploys from the day before: a deploy restarts the server and the book is re-scored in the
  background for ten minutes.
- Say the £100 as "one hundred pounds". Read the reasons off the screen rather than from memory;
  they are facts about the account, not inferences about the person.
- "Dior" is the hypothetical in the script; the store on screen says Maison Aurelle, which is
  fictional. Nobody in it exists.
