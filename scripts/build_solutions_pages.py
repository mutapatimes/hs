"""Generate the per-industry Halia solutions pages (web/site/solutions/<slug>.html).

Each page tells one clear story: (1) the problem — in this industry, transaction value is a bad
proxy for customer value; (2) a single buyer you can't see, with an LTV chart of current spend vs
latent potential; (3) proof — a "same spend, different worth" table showing how Halia separates
lookalikes; (4) the solution — what Halia surfaces and the move. Data-forward, simple layout.

Content lives in INDUSTRIES below (edit freely). Brand shell mirrors web/site/solutions.html.

    python scripts/build_solutions_pages.py     # writes web/site/solutions/*.html

Routing: app.py serves /solutions/<slug>. The /solutions hub + the nav dropdown link them.
Standalone: stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "site" / "solutions"


def gbp(n: int) -> str:
    if n >= 1000:
        return f"£{n // 1000}k" if n % 1000 == 0 else f"£{n / 1000:.1f}k"
    return f"£{n:,}"


# Each industry: the problem framing, one worked buyer (with an LTV gap), three same-spend
# lookalikes for the table, and the solution. Money is in whole £.
INDUSTRIES = [
    {
        "slug": "fashion", "name": "Fashion & apparel", "eyebrow": "Solutions · Fashion",
        "h1": "The first modest order that hides your next <em>house client.</em>",
        "lede": "In fashion, a small first order can belong to a stylist, a celebrity's PA, or a "
                "Mayfair address — and a spend threshold treats them like everyone else.",
        "problem": "A new client testing you with one piece looks identical to a bargain-hunter. Both "
                   "spent £150. One has a five-figure wardrobe ceiling and a stylist on speed-dial; the "
                   "other you will never see again.",
        "low": "£150 first order", "high": "£40k annual wardrobe",
        "buyer_line": "A £150 first order — W1 billing, a private-domain email, paid on a premium card.",
        "buyer_spend": 150, "buyer_spend_note": "spent so far",
        "buyer_cadence": "One order, 3 weeks ago",
        "buyer_signals": ["Prime postcode (W1)", "Premium card", "Private domain"],
        "buyer_grade": "A*", "buyer_latent": 38000,
        "rows": [
            ("Stylist · W1 · PA email", 150, "Prime postcode + PA order", "A*", 38000, True),
            ("Gifter · regional · gmail", 150, "None of note", "C", 300, False),
            ("Sale-only shopper · gmail", 150, "Discount-led, one-off", "C", 200, False),
        ],
        "surfaces": ["Celebrity stylists", "Prime postcodes", "Premium cards", "Company & PA orders"],
        "move": "Halia flags the tell the moment the order lands and hands your clienteling team a "
                "ready gesture — a private appointment, early access to the drop — in Shopify and "
                "Klaviyo, before it sells out.",
    },
    {
        "slug": "wine", "name": "Wine & spirits", "eyebrow": "Solutions · Wine & spirits",
        "h1": "The quiet regular who turns out to be a <em>serious collector.</em>",
        "lede": "Collectors buy everyday drinking wine between allocations, so the person quietly "
                "ordering modest bottles is invisible to spend-based logic — exactly wrong for the "
                "client who should be first on the en-primeur list.",
        "problem": "One book holds £12 bottles and £12,000 cases. Spend on any single order tells you "
                   "almost nothing about whose cellar deserves the allocation call.",
        "low": "£15 midweek bottles", "high": "£12,000 en-primeur case",
        "buyer_line": "Four £15 bottles a month, shipped to St Helier, Jersey.",
        "buyer_spend": 720, "buyer_spend_note": "per year, today",
        "buyer_cadence": "Monthly, small, steady",
        "buyer_signals": ["Jersey (high-value jurisdiction)", "Family-office email", "Steady cadence"],
        "buyer_grade": "A*", "buyer_latent": 14000,
        "rows": [
            ("Jersey · monthly · family-office email", 720, "High-value jurisdiction", "A*", 14000, True),
            ("London SW · monthly · premium email", 720, "Prime postcode", "A", 6200, False),
            ("One-off gift · regional", 180, "None; won't return", "C", 0, False),
        ],
        "surfaces": ["HNW postcodes & jurisdictions", "Prime residences", "Family-office billing",
                     "Order frequency"],
        "move": "Halia ranks your quiet collectors by the wealth behind their modest orders, so the "
                "rare-allocation call, the en-primeur invite, and the private tasting reach the people "
                "most likely to say yes. Allocation lists are already clienteling — this systematises them.",
    },
    {
        "slug": "beauty", "name": "Beauty & fragrance", "eyebrow": "Solutions · Beauty & fragrance",
        "h1": "A £30 lipstick looks the same <em>whoever buys it.</em>",
        "lede": "Bought by a nurse or an heiress, the transaction is identical — but one of those "
                "customers has a five-figure skincare-and-fragrance ceiling. Entry-level luxury is how "
                "the wealthy shop casually.",
        "problem": "Beauty runs on enormous one-time and gifting volume, clustered at low price points "
                   "and mostly never nurtured. The casual gifter and the regular-in-waiting look the same.",
        "low": "£30 first order", "high": "£8k a year in skincare & scent",
        "buyer_line": "A £34 fragrance, gift-wrapped, a legacy premium email, a Notting Hill address.",
        "buyer_spend": 34, "buyer_spend_note": "spent so far",
        "buyer_cadence": "One order",
        "buyer_signals": ["HNW neighbourhood", "Legacy premium email", "Gift order"],
        "buyer_grade": "A", "buyer_latent": 7800,
        "rows": [
            ("Notting Hill · legacy premium email", 34, "HNW neighbourhood", "A", 7800, True),
            ("Regional · gmail · sale item", 34, "Discount-led", "C", 90, False),
            ("Corporate gift bulk · one-off", 340, "Company, one-time", "C", 260, False),
        ],
        "surfaces": ["Premium & legacy email", "HNW neighbourhoods", "Concierge delivery",
                     "Assistant orders"],
        "move": "Halia separates the quiet high-ceiling customer from the crowd and pushes them into a "
                "private-shopping invite or a founder note through Klaviyo — the score-to-segment "
                "pipeline you already run, pointed at the right faces.",
    },
    {
        "slug": "jewellery", "name": "Jewellery & watches", "eyebrow": "Solutions · Jewellery & watches",
        "h1": "A £120 strap buyer hiding a <em>£50,000 collector.</em>",
        "lede": "In high-AOV categories a small first purchase is a test. The second can be "
                "life-changing for the relationship — if you reach the right person while the interest "
                "is still warm.",
        "problem": "The test purchase and the impulse buy look identical. Spend-based ranking can't tell "
                   "a future commission from a one-off, so the personal follow-up never happens.",
        "low": "£140 accessory", "high": "£50k commission",
        "buyer_line": "A £140 strap — a premium-card BIN, a family-office email domain.",
        "buyer_spend": 140, "buyer_spend_note": "spent so far",
        "buyer_cadence": "One order",
        "buyer_signals": ["Family office", "Premium card BIN", "Prime residence"],
        "buyer_grade": "A*", "buyer_latent": 46000,
        "rows": [
            ("Family-office domain · prime residence", 140, "Wealth structure", "A*", 46000, True),
            ("Gift buyer · standard card", 140, "None of note", "C", 400, False),
            ("Repair/strap only · regional", 140, "Service, not a buyer", "C", 250, False),
        ],
        "surfaces": ["Family offices", "Prime residences", "Premium card BINs", "Honorifics"],
        "move": "Halia grades the wealth behind the first order and flags it for a named contact, so the "
                "second conversation is personal and timely — routed to the client's Shopify profile and "
                "your CRM, not a mass email.",
    },
    {
        "slug": "home", "name": "Home, furniture & interiors", "eyebrow": "Solutions · Home & interiors",
        "h1": "The cushion buyer hiding a <em>whole-house project.</em>",
        "lede": "Interior designers, stylists, and trade buyers place orders that look ordinary and "
                "recur for years. One accessory can be the front of a five-figure specification.",
        "problem": "A designer testing your quality with one item looks like any retail shopper — but "
                   "they buy for clients, repeatedly. Miss the tell and a trade relationship goes to a "
                   "competitor over a one-off discount.",
        "low": "£75 accessory", "high": "£40k room specification",
        "buyer_line": "A £75 order — company billing, repeat delivery to a Chelsea address.",
        "buyer_spend": 450, "buyer_spend_note": "per year, today",
        "buyer_cadence": "Three orders in six weeks",
        "buyer_signals": ["Company / trade billing", "Repeat prime address", "Trophy postcode"],
        "buyer_grade": "A*", "buyer_latent": 40000,
        "rows": [
            ("Company billing · repeat Chelsea address", 450, "Trade pattern", "A*", 40000, True),
            ("One home refresh · prime postcode", 450, "Prime address", "A", 4200, False),
            ("Single gift · regional", 75, "None of note", "C", 120, False),
        ],
        "surfaces": ["Company & trade billing", "Repeat delivery addresses", "Trophy addresses",
                     "Prime postcodes"],
        "move": "Halia spots company billing, recurring addresses, and prime locations, so you can offer "
                "terms and a dedicated contact — the difference between a single sale and a multi-year "
                "trade account.",
    },
    {
        "slug": "gifting", "name": "Flowers, food & gifting", "eyebrow": "Solutions · Flowers, food & gifting",
        "h1": "The standing weekly order that hides a <em>house account.</em>",
        "lede": "In flowers, food, and gifting, the modest recurring order is often the wealthy one — "
                "and a standing subscription can sit in front of an events and corporate budget many "
                "times its size.",
        "problem": "A £48 weekly subscription looks tiny beside a corporate order, so the standing-order "
                   "customer ranks at the bottom — exactly wrong for the household most likely to have an "
                   "events and gifting budget. And a subscriber gives you the richest signal of all: they "
                   "come back every week.",
        "low": "£48 weekly subscription", "high": "£11k events & corporate gifting",
        "buyer_line": "A £48 standing weekly delivery to SW1, placed by an assistant.",
        "buyer_spend": 2500, "buyer_spend_note": "per year, subscription",
        "buyer_cadence": "Weekly, standing order",
        "buyer_signals": ["Prime postcode (SW1)", "Assistant-placed", "Company billing on file"],
        "buyer_grade": "A*", "buyer_latent": 11000,
        "rows": [
            ("Standing weekly · SW1 · PA-placed", 2500, "Prime + assistant + company", "A*", 11000, True),
            ("Occasional gifter · regional", 120, "None of note", "C", 160, False),
            ("One-off Valentine's order", 60, "Seasonal, one-time", "C", 0, False),
        ],
        "surfaces": ["Prime postcodes & residences", "Standing-order cadence", "Assistant orders",
                     "Company billing"],
        "move": "Halia flags the well-heeled, PA-placed, or company-billed subscriber and prompts the "
                "conversation the retail order never triggers — a house account, the events and corporate "
                "budget — before it goes somewhere else.",
    },
    {
        "slug": "collectibles", "name": "Rare books & collectibles", "eyebrow": "Solutions · Rare books & collectibles",
        "h1": "£20 paperbacks and £8,000 first editions, <em>one till.</em>",
        "lede": "A serious collector buys everyday reading beside the rare piece. The trade knows this "
                "by instinct; nobody has systematised it.",
        "problem": "In rare books, prints, and coins, the base of modest purchases is full of serious "
                   "collectors quietly building. Any single order's value tells you almost nothing about "
                   "who is worth a catalogue call.",
        "low": "£20 reading copy", "high": "£8,000 first edition",
        "buyer_line": "A steady run of £20–£40 orders to a prime address, from a bibliophile's own domain.",
        "buyer_spend": 240, "buyer_spend_note": "per year, today",
        "buyer_cadence": "Monthly, small, steady",
        "buyer_signals": ["Prime address", "Custom domain", "Steady cadence"],
        "buyer_grade": "A", "buyer_latent": 9000,
        "rows": [
            ("Prime address · custom domain · monthly", 240, "Collector pattern", "A", 9000, True),
            ("Student · gmail · occasional", 240, "None of note", "C", 260, False),
            ("One gift order · regional", 40, "Seasonal, one-time", "C", 0, False),
        ],
        "surfaces": ["Prime addresses", "Premium & custom domains", "Honorifics", "Order frequency"],
        "move": "Halia ranks the quiet buyers most likely to be building a collection, so early offers "
                "and catalogue previews reach them first — the systematised version of what your best "
                "dealer already does on a hunch.",
    },
    {
        "slug": "electronics", "name": "Electronics & big-box", "eyebrow": "Solutions · Electronics & big-box",
        "h1": "In a book this big, the high-value buyer is <em>invisible.</em>",
        "lede": "High-street and big-box electronics move enormous volume at every price point. A £40 "
                "cable and a £4,000 fit-out sit in the same database — and the multi-property or trade "
                "buyer is lost in it.",
        "problem": "When millions of orders span every wealth level, transaction value tells you nothing "
                   "about lifetime potential. The landlord kitting out ten flats and the household "
                   "mid-renovation both look like single small sales.",
        "low": "£40 accessory", "high": "£40k multi-property / trade fit-out",
        "buyer_line": "Three £40 orders to three different postcodes, one billing address.",
        "buyer_spend": 120, "buyer_spend_note": "spent so far",
        "buyer_cadence": "Three orders, three addresses",
        "buyer_signals": ["Multi-address pattern", "Company / trade billing", "Multiple prime postcodes"],
        "buyer_grade": "A*", "buyer_latent": 40000,
        "rows": [
            ("One billing addr · 3 delivery postcodes", 120, "Multi-property / trade", "A*", 40000, True),
            ("Single household order", 120, "None of note", "C", 300, False),
            ("Gift to one address", 120, "One-time", "C", 150, False),
        ],
        "surfaces": ["Multi-address patterns", "Company & trade billing", "Prime & multiple postcodes",
                     "Premium cards"],
        "move": "Here Halia is lead qualification for your business / premium division — surfacing the "
                "trade, landlord, and high-ceiling households hiding in retail volume, so a human account "
                "team can reach them. The engine is the same; the buyer on your side is a premium-account "
                "function rather than a clienteling desk.",
    },
]

_NAV_MENU = "".join(
    f'<a href="/solutions/{i["slug"]}">{i["name"]}</a>' for i in INDUSTRIES
) + '<a class="all" href="/solutions">All solutions &rarr;</a>'

_CSS = """
  :root{--bg:#f5f2ea;--bg-2:#efeadd;--ink:#1a1712;--mute:#615b50;--faint:#9a9385;--gold:#7a7363;
    --line:rgba(20,18,12,.14);--line-2:rgba(20,18,12,.07);
    --serif:'Cormorant Garamond',Georgia,serif;--sans:'Inter',-apple-system,system-ui,sans-serif}
  *{box-sizing:border-box}html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
  a{color:inherit;text-decoration:none}::selection{background:#1a1712;color:#f5f2ea}
  .wrap{max-width:1120px;margin:0 auto;padding:0 40px}.narrow{max-width:820px}
  .eyebrow{font:500 12px/1 var(--sans);letter-spacing:.32em;text-transform:uppercase;color:var(--gold)}
  h1,h2,h3{font-family:var(--serif);font-weight:300;letter-spacing:-.01em;margin:0;line-height:1.05}
  .display{font-size:clamp(42px,6.4vw,80px)}.h2{font-size:clamp(28px,4vw,46px)}
  em{font-style:italic;color:var(--gold)}
  .lede{font-size:clamp(18px,2vw,21px);color:var(--mute);line-height:1.5}
  .btn{display:inline-flex;align-items:center;gap:10px;font:500 14px var(--sans);padding:14px 26px;border-radius:999px;border:1px solid var(--ink);color:#f5f2ea;background:var(--ink);transition:.25s;cursor:pointer}
  .btn:hover{background:transparent;color:var(--ink)}.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}.btn.ghost:hover{border-color:var(--ink)}
  .arrow{transition:transform .25s}.btn:hover .arrow{transform:translateX(4px)}
  header{position:fixed;inset:0 0 auto;z-index:40;transition:.3s}header.solid{background:rgba(245,242,234,.82);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
  .nav{display:flex;align-items:center;justify-content:space-between;height:78px}
  .brand{display:flex;align-items:center;gap:11px;font-family:var(--serif);font-size:26px}
  .nav-links{display:flex;gap:32px;align-items:center;height:100%}.nav-links a{font:500 14px var(--sans);color:var(--mute)}.nav-links a:hover{color:var(--ink)}
  .nav .right{display:flex;gap:20px;align-items:center}.nav .right .si{font:500 14px var(--sans);color:var(--mute)}
  @media(max-width:900px){.nav-links{display:none}}
  .burger{display:none;align-items:center;justify-content:center;width:42px;height:42px;border-radius:11px;border:1px solid var(--line);background:transparent;color:var(--ink);cursor:pointer;flex:none;padding:0}
  .burger svg{width:20px;height:20px}
  .mscrim{position:fixed;inset:0;background:rgba(10,10,11,.5);opacity:0;visibility:hidden;transition:opacity .3s;z-index:55}.mscrim.show{opacity:1;visibility:visible}
  .mdrawer{position:fixed;top:0;right:0;bottom:0;width:min(84vw,330px);background:var(--bg);border-left:1px solid var(--line);z-index:60;transform:translateX(100%);transition:transform .32s cubic-bezier(.2,.7,.2,1);display:flex;flex-direction:column;padding:22px 26px 30px;overflow-y:auto}
  .mdrawer.show{transform:none}
  .mdrawer .mclose{align-self:flex-end;background:none;border:none;color:var(--mute);font-size:28px;line-height:1;cursor:pointer;padding:2px 4px;margin-bottom:6px}
  .mdrawer a{font:500 17px var(--sans);color:var(--ink);padding:14px 0;border-bottom:1px solid var(--line-2)}
  .mdrawer a.msi{color:var(--mute);font-size:15px}
  .mdrawer a.mcta{margin-top:20px;border:none;background:var(--ink);color:var(--bg);text-align:center;border-radius:999px;padding:15px;font-weight:600}
  @media(max-width:900px){.burger{display:inline-flex}}
  section{position:relative}
  .reveal{opacity:0;transform:translateY(24px);transition:opacity .9s cubic-bezier(.2,.6,.2,1),transform .9s cubic-bezier(.2,.6,.2,1)}.reveal.in{opacity:1;transform:none}.reveal.d1{transition-delay:.08s}.reveal.d2{transition-delay:.16s}
  @media(prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none}}
  .ip-hero{padding:150px 0 20px}.ip-hero h1{margin:16px 0 22px;max-width:19ch}.ip-hero .lede{max-width:56ch}
  .sec{padding:clamp(46px,7vh,84px) 0;border-top:1px solid var(--line-2)}
  .sec .k{font:500 12px var(--sans);letter-spacing:.3em;text-transform:uppercase;color:var(--gold);margin-bottom:14px}
  .sec h2{margin-bottom:14px;max-width:22ch}.sec .p{color:var(--mute);font-size:17px;max-width:60ch}
  .pc{display:flex;flex-wrap:wrap;margin-top:30px;border:1px solid var(--line);border-radius:14px;overflow:hidden;max-width:640px}
  .pc>div{flex:1 1 220px;padding:22px 24px}.pc .hi{background:var(--ink);color:var(--bg)}
  .pc .l{font:500 11px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin-bottom:8px}.pc .hi .l{color:rgba(245,242,234,.6)}
  .pc .v{font-family:var(--serif);font-size:clamp(22px,3vw,30px);line-height:1.05}
  .ex{display:grid;grid-template-columns:1fr 1fr;gap:clamp(22px,4vw,52px);align-items:center;margin-top:12px}
  @media(max-width:820px){.ex{grid-template-columns:1fr;gap:26px}}
  .exc{border:1px solid var(--line);border-radius:16px;padding:26px 28px;background:var(--bg-2)}
  .exc .line{font-family:var(--serif);font-size:clamp(20px,2.5vw,25px);line-height:1.22;margin-bottom:18px}
  .exrow{display:flex;gap:26px;flex-wrap:wrap;margin-bottom:16px}
  .exrow .m .l{font:500 11px var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--faint);margin-bottom:2px}
  .exrow .m .v{font-family:var(--serif);font-size:21px}
  .exrow .m .v .g{display:inline-block;background:var(--ink);color:var(--bg);border-radius:999px;padding:2px 11px;font:600 13px var(--sans)}
  .chips{display:flex;flex-wrap:wrap;gap:7px}.chip{font:500 12px var(--sans);color:var(--mute);border:1px solid var(--line);padding:5px 11px;border-radius:999px}
  .ltv .l{font:500 11px var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin-bottom:12px}
  .bar{height:38px;border-radius:9px;display:flex;align-items:center;padding:0 14px;color:#fff;font:600 14px var(--sans);white-space:nowrap;margin-bottom:10px;min-width:64px;transition:width 1s cubic-bezier(.2,.6,.2,1)}
  .bar.now{background:var(--faint)}.bar.pot{background:var(--gold)}
  .ltv .cap{color:var(--mute);font-size:13px;margin-top:6px}
  .tbl-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:14px;margin-top:30px}
  table.lt{width:100%;border-collapse:collapse;font-size:14px;min-width:600px}
  table.lt th{text-align:left;padding:12px 16px;background:var(--bg-2);color:var(--faint);font:600 10.5px var(--sans);letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
  table.lt th.r,table.lt td.r{text-align:right}
  table.lt td{padding:13px 16px;border-top:1px solid var(--line-2);color:var(--mute)}
  table.lt td.who{color:var(--ink)}
  table.lt tr.hot td{background:rgba(122,115,99,.09)}
  table.lt .g{font-weight:700;color:var(--ink)}table.lt .lat{font-family:var(--serif);font-size:18px;color:var(--ink)}
  .surfaces .sl{font:500 11px var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin:6px 0 14px}
  .tags{display:flex;flex-wrap:wrap;gap:9px}.tag{font:500 13px var(--sans);color:var(--mute);border:1px solid var(--line);padding:7px 13px;border-radius:999px}
  .others .sl{font:500 11px var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin-bottom:14px}
  .others .row{display:flex;flex-wrap:wrap;gap:10px}
  .others a{font:500 13.5px var(--sans);color:var(--mute);border:1px solid var(--line);padding:9px 15px;border-radius:999px}.others a:hover{border-color:var(--ink);color:var(--ink)}
  .final{text-align:center}.final h2{margin-bottom:16px}.pad{padding:clamp(70px,10vh,120px) 0}
  footer{border-top:1px solid var(--line);padding:60px 0 44px;margin-top:20px}
"""

_ASTER = "&#8258;"


def _nav() -> str:
    return (
        '<header id="hdr"><div class="wrap nav">'
        f'<a class="brand" href="/"><span aria-hidden="true" style="font-family:\'Cormorant Garamond\',Georgia,serif;font-size:22px;line-height:1;color:#d8d2c6">{_ASTER}</span>Halia</a>'
        '<nav class="nav-links"><a href="/#how">How it works</a><a href="/clienteling">Clienteling</a>'
        f'<span class="nav-drop"><a href="/solutions">Solutions</a><div class="nav-menu">{_NAV_MENU}</div></span>'
        '<a href="/pricing">Pricing</a><a href="/security">Security</a><a href="/faq">FAQ</a></nav>'
        '<div class="right"><a class="si" href="/#demo">See a demo</a><a class="si" href="/app">Sign in</a>'
        '<a class="btn" href="/connect">Connect your store <span class="arrow">&rarr;</span></a>'
        '<button class="burger" id="burger" aria-label="Open menu"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg></button></div>'
        '</div></header>'
        '<div class="mscrim" id="mscrim"></div>'
        '<aside class="mdrawer" id="mdrawer" aria-hidden="true">'
        '<button class="mclose" id="mclose" aria-label="Close menu">&times;</button>'
        '<a href="/#how">How it works</a><a href="/clienteling">Clienteling</a><a href="/solutions">Solutions</a>'
        '<a href="/pricing">Pricing</a><a href="/security">Security</a><a href="/faq">FAQ</a>'
        '<a class="msi" href="/#demo">See a demo</a><a class="msi" href="/app">Sign in</a>'
        '<a class="mcta" href="/connect">Connect your store</a></aside>'
    )


def _footer() -> str:
    return (
        '<footer class="hfoot"><div class="hf-inner">'
        '<div class="hf-news"><h3>The quiet edge in luxury retail, in your inbox.</h3>'
        '<form id="newsForm" novalidate><input id="newsEmail" type="email" placeholder="Your work email" required>'
        '<button type="submit">Subscribe &rarr;</button></form></div>'
        '<div class="hf-grid"><div>'
        f'<a class="brand" href="/"><span aria-hidden="true" style="font-family:\'Cormorant Garamond\',Georgia,serif;font-size:22px;line-height:1;color:var(--gold,#8a8377)">{_ASTER}</span>Halia</a>'
        '<p class="hf-bio">Halia is hidden-VIC intelligence for considered-purchase retail. We read the '
        'wealth and intent signals already sitting in your customer data, grade every customer, and '
        'surface the high-value clients you would otherwise treat like everyone else, then help your '
        'teams act on them in the tools they already use. We never keep a copy of your customers: they '
        'are scored on the spot and nothing about them is stored on our side.</p></div>'
        '<div class="hf-col"><h4>Product</h4><a href="/#engine">The engine</a><a href="/#how">How it works</a>'
        '<a href="/#signals">Signals</a><a href="/#teams">For teams</a><a href="/connect">Connect a store</a></div>'
        '<div class="hf-col"><h4>Company</h4><a href="/clienteling">Clienteling</a><a href="/solutions">Solutions</a>'
        '<a href="/pricing">Pricing</a><a href="/security">Security</a><a href="/faq">FAQ</a>'
        '<a href="/responsible">Responsible profiling</a><a href="/status">System status</a><a href="/brand">Brand</a>'
        '<a href="mailto:hello@halia.app">Contact</a></div>'
        '<div class="hf-col"><h4>Legal</h4><a href="/privacy">Privacy Policy</a><a href="/terms">Terms of Service</a>'
        '<a href="/cookies">Cookie Policy</a><a href="/security">Security &amp; compliance</a></div></div>'
        '<div class="hf-bot"><span>&copy; 2026 Halia. All rights reserved.</span>'
        '<span>Zero-retention by design &middot; Shopify &middot; WooCommerce &middot; Klaviyo &middot; Mailchimp</span>'
        '</div></div></footer>'
    )


_SCRIPT = (
    "<script>var hdr=document.getElementById('hdr');addEventListener('scroll',function(){"
    "hdr.classList.toggle('solid',scrollY>40)},{passive:true});(function(){var b=document.getElementById('burger'),"
    "d=document.getElementById('mdrawer'),s=document.getElementById('mscrim'),c=document.getElementById('mclose');"
    "if(!d)return;function o(){d.classList.add('show');s.classList.add('show');d.setAttribute('aria-hidden','false')}"
    "function x(){d.classList.remove('show');s.classList.remove('show');d.setAttribute('aria-hidden','true')}"
    "if(b)b.onclick=o;if(c)c.onclick=x;if(s)s.onclick=x;d.querySelectorAll('a').forEach(function(a){a.addEventListener('click',x)})})();"
    "var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');"
    "io.unobserve(e.target)}})},{threshold:.14,rootMargin:'0px 0px -8% 0px'});"
    "document.querySelectorAll('.reveal:not(.in)').forEach(function(el){io.observe(el)});</script>"
)


def _others(current: str) -> str:
    links = "".join(f'<a href="/solutions/{i["slug"]}">{i["name"]}</a>'
                    for i in INDUSTRIES if i["slug"] != current)
    return ('<section class="sec"><div class="wrap"><div class="others reveal">'
            '<div class="sl">Halia by industry</div><div class="row">'
            f'<a href="/solutions">All solutions</a>{links}</div></div></div></section>')


def _rows(ind: dict) -> str:
    out = []
    for who, spend, signal, grade, latent, hot in ind["rows"]:
        lat = gbp(latent) if latent else "&mdash;"
        out.append(
            f'<tr class="{"hot" if hot else ""}"><td class="who">{who}</td>'
            f'<td class="r">{gbp(spend)}</td><td>{signal}</td>'
            f'<td class="g">{grade}</td><td class="r lat">{lat}</td></tr>')
    return "".join(out)


def render(ind: dict) -> str:
    now, pot = ind["buyer_spend"], ind["buyer_latent"]
    now_w = max(7, round(now / pot * 100)) if pot else 7      # keep the "now" bar visible
    signals = "".join(f'<span class="chip">{s}</span>' for s in ind["buyer_signals"])
    tags = "".join(f'<span class="tag">{t}</span>' for t in ind["surfaces"])
    body = f"""
<section class="ip-hero"><div class="wrap">
  <div class="eyebrow reveal in">{ind["eyebrow"]}</div>
  <h1 class="display reveal in d1">{ind["h1"]}</h1>
  <p class="lede reveal in d1">{ind["lede"]}</p>
</div></section>

<section class="sec"><div class="wrap">
  <div class="k reveal">The problem</div>
  <p class="p reveal" style="font-size:19px;color:var(--ink);max-width:52ch">{ind["problem"]}</p>
  <div class="pc reveal d1">
    <div><div class="l">A transaction that looks like</div><div class="v">{ind["low"]}</div></div>
    <div class="hi"><div class="l">From a client who could be worth</div><div class="v">{ind["high"]}</div></div>
  </div>
</div></section>

<section class="sec"><div class="wrap">
  <div class="k reveal">A buyer you can't see</div>
  <div class="ex">
    <div class="exc reveal">
      <div class="line">{ind["buyer_line"]}</div>
      <div class="exrow">
        <div class="m"><div class="l">Spend</div><div class="v">{gbp(now)}</div></div>
        <div class="m"><div class="l">Cadence</div><div class="v" style="font-size:15px">{ind["buyer_cadence"]}</div></div>
        <div class="m"><div class="l">Halia grade</div><div class="v"><span class="g">{ind["buyer_grade"]}</span></div></div>
      </div>
      <div class="chips">{signals}</div>
    </div>
    <div class="ltv reveal d1">
      <div class="l">Value now vs. latent potential</div>
      <div class="bar now" style="width:{now_w}%">{gbp(now)} <span style="opacity:.85;font-weight:500">&nbsp;{ind["buyer_spend_note"]}</span></div>
      <div class="bar pot" style="width:100%">{gbp(pot)} <span style="opacity:.9;font-weight:500">&nbsp;latent / yr</span></div>
      <div class="cap">The gap between what they spend today and what they're worth nurtured &mdash; the number spend-based ranking can't see.</div>
    </div>
  </div>
</div></section>

<section class="sec"><div class="wrap">
  <div class="k reveal">Same spend, different worth</div>
  <h2 class="h2 reveal">Three buyers, one price point.</h2>
  <p class="p reveal" style="margin-top:12px">Identical recent spend &mdash; but Halia grades them on the wealth and intent behind the order, and estimates what each is worth if nurtured.</p>
  <div class="tbl-wrap reveal d1"><table class="lt">
    <thead><tr><th>Customer</th><th class="r">Recent spend</th><th>What Halia reads</th><th>Grade</th><th class="r">Est. latent / yr</th></tr></thead>
    <tbody>{_rows(ind)}</tbody>
  </table></div>
</div></section>

<section class="sec"><div class="wrap">
  <div class="k reveal">What Halia does</div>
  <h2 class="h2 reveal">Find them, then make the move.</h2>
  <div class="surfaces reveal d1"><div class="sl">Signals it reads, from data you already hold</div><div class="tags">{tags}</div></div>
  <p class="p reveal d1" style="margin-top:26px">{ind["move"]}</p>
</div></section>

{_others(ind["slug"])}

<section class="pad final"><div class="wrap reveal">
  <div class="eyebrow" style="margin-bottom:22px">Begin</div>
  <h2 class="h2">See who you have been missing.</h2>
  <p class="lede" style="max-width:36ch;margin:14px auto 32px">Connect your store and Halia surfaces your hidden VICs, usually within the hour.</p>
  <a class="btn" href="/connect">Connect your store <span class="arrow">&rarr;</span></a>
</div></section>
"""
    return (
        "<!doctype html><html lang=\"en\"><head>"
        "<link rel=\"stylesheet\" href=\"/static/brand.css\"><script src=\"/static/brand.js\" defer></script>"
        f"<link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%237a7363'>{_ASTER}</text></svg>\">"
        "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{ind['name']} · Halia</title>"
        f"<meta name=\"description\" content=\"Halia for {ind['name'].lower()}: the high-value clients hiding in a book full of low-ticket orders, with the latent value they represent and the move to win them.\">"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
        "<link href=\"https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter:wght@400;500&display=swap\" rel=\"stylesheet\">"
        f"<style>{_CSS}</style></head><body>"
        f"{_nav()}{body}{_footer()}{_SCRIPT}</body></html>"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ind in INDUSTRIES:
        (OUT / f"{ind['slug']}.html").write_text(render(ind), encoding="utf-8")
    print(f"Wrote {len(INDUSTRIES)} industry pages to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
