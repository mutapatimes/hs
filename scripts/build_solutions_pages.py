"""Generate the per-industry Halia solutions pages (web/site/solutions/<slug>.html).

Each page makes the same argument in the industry's own language: transaction value is a bad proxy
for customer value, so the high-potential clients hide in a book full of low-ticket orders — and
here is exactly what Halia surfaces and the move it hands your team. Content lives in INDUSTRIES
below (edit freely); the brand shell (head/nav/footer) mirrors web/site/solutions.html.

    python scripts/build_solutions_pages.py     # writes web/site/solutions/*.html

Routing: app.py serves /solutions/<slug> from these files. The /solutions hub links them.
Standalone: stdlib only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "site" / "solutions"

# (slug, name) in display order — the sequence in the go-to-market plan.
INDUSTRIES = [
    {
        "slug": "fashion", "name": "Fashion & apparel", "eyebrow": "Solutions · Fashion",
        "h1": "The first modest order that hides your next <em>house client.</em>",
        "lede": "Luxury and contemporary fashion runs on relationships — but a £120 first order can "
                "belong to a stylist, a celebrity's PA, or a Mayfair address, and a spend threshold "
                "treats them like everyone else.",
        "problem_h2": "Spend today is a poor guide to spend tomorrow.",
        "problem_p": "A new client testing you with one piece looks identical to a bargain-hunter — "
                     "both spent £120. One has a five-figure wardrobe ceiling and a stylist on "
                     "speed-dial; the other you will never see again. Your export can't tell them apart.",
        "low": "£120 first order", "high": "£40k annual wardrobe",
        "case_line": "A £150 order, a W1 billing address, a private-domain email — one small sale.",
        "case_reveal": "a personal shopper buying for three UHNW clients. The account you most want, "
                       "arriving disguised as a modest first order.",
        "surfaces": ["Celebrity stylists", "Prime postcodes", "Premium cards", "Company & PA orders",
                     "Concierge delivery"],
        "move_h2": "Open a private line before the next drop.",
        "move_p": "The moment the order lands, Halia flags the tell and hands your clienteling team a "
                  "ready gesture — a private appointment, early access to the drop — inside Shopify and "
                  "Klaviyo, before it sells out, not after.",
        "pull": "",
    },
    {
        "slug": "wine", "name": "Wine & spirits", "eyebrow": "Solutions · Wine & spirits",
        "h1": "The quiet regular who turns out to be a <em>serious collector.</em>",
        "lede": "Every merchant has the story: the customer buying four £15 bottles a month who, it "
                "turns out, has a cellar worth more than the shop. Halia finds them before someone "
                "else makes the allocation call.",
        "problem_h2": "One book holds £12 bottles and £12,000 cases.",
        "problem_p": "Collectors buy everyday drinking wine between allocations, so the person quietly "
                     "ordering modest bottles from a Jersey address is invisible to spend-based logic "
                     "— and invisible is exactly wrong for the client who should be first on the "
                     "en-primeur list.",
        "low": "£15 midweek bottles", "high": "£12,000 en-primeur case",
        "case_line": "Four £15 bottles a month, shipped to St Helier, Jersey.",
        "case_reveal": "a collector between allocations. Today's logic ranks them beside a student, so "
                       "the allocation call goes to whoever happens to be louder.",
        "surfaces": ["HNW postcodes & jurisdictions", "Prime residences", "Premium email",
                     "Company & family-office billing", "Order frequency & recency"],
        "move_h2": "Make the allocation call to the right cellar.",
        "move_p": "Halia grades the wealth signals behind modest orders and ranks your quiet "
                  "collectors, so the rare-allocation call, the en-primeur invite, and the private "
                  "tasting reach the people most likely to say yes. Allocation lists are already "
                  "clienteling — this is the systematised version.",
        "pull": "You already believe this — you have met the quiet regular who turned out to be a "
                "major collector. Halia makes finding them repeatable.",
    },
    {
        "slug": "beauty", "name": "Beauty & fragrance", "eyebrow": "Solutions · Beauty & fragrance",
        "h1": "A £30 lipstick looks the same <em>whoever buys it.</em>",
        "lede": "Bought by a nurse or an heiress, the transaction is identical — but one of those "
                "customers has a five-figure skincare-and-fragrance ceiling. Entry-level luxury is "
                "exactly how the wealthy shop casually.",
        "problem_h2": "Your densest hiding place is the low-ticket repeat.",
        "problem_p": "Beauty runs on enormous one-time and gifting volume, most of it clustered at low "
                     "price points and most of it never nurtured. The casual gifter and the "
                     "regular-in-waiting look identical in the export.",
        "low": "£30 first order", "high": "£8k a year in skincare & scent",
        "case_line": "A £34 fragrance, gift-wrapped, a legacy premium email, a Notting Hill address.",
        "case_reveal": "not a one-off gifter — a client who would spend heavily on the brand if anyone "
                       "recognised her. Right now she drops into lifecycle with everyone else.",
        "surfaces": ["Premium & legacy email", "HNW neighbourhoods", "Concierge delivery",
                     "Assistant orders", "Custom domains"],
        "move_h2": "Turn casual buyers into house clients.",
        "move_p": "Halia separates the quiet high-ceiling customer from the crowd and pushes them into "
                  "a private-shopping invite or a founder note through Klaviyo — the score-to-segment "
                  "pipeline you already run, finally pointed at the right faces.",
        "pull": "",
    },
    {
        "slug": "jewellery", "name": "Jewellery & watches", "eyebrow": "Solutions · Jewellery & watches",
        "h1": "A £120 strap buyer hiding a <em>£50,000 collector.</em>",
        "lede": "In high-AOV categories a small first purchase is a test. The second can be "
                "life-changing for the relationship — if you reach the right person while the "
                "interest is still warm.",
        "problem_h2": "The test purchase and the impulse buy look identical.",
        "problem_p": "Someone buying an accessory or an entry piece may be sizing you up for a serious "
                     "commission. Spend-based ranking can't tell them from a one-off, so the personal "
                     "follow-up never happens — or reaches the wrong client.",
        "low": "£120 accessory", "high": "£50k commission",
        "case_line": "A £140 strap, a premium-card BIN, a family-office email domain.",
        "case_reveal": "a collector testing the water. A personal call now is a commission; a generic "
                       "order receipt is a lost relationship.",
        "surfaces": ["Family offices", "Prime residences", "Premium card BINs",
                     "Honorifics & post-nominals", "Wealth structures"],
        "move_h2": "A personal follow-up while the interest is warm.",
        "move_p": "Halia grades the wealth behind the first order and flags it for a named contact, so "
                  "the second conversation is personal and timely — routed straight to the client's "
                  "Shopify profile and your CRM, not a mass email.",
        "pull": "",
    },
    {
        "slug": "home", "name": "Home, furniture & interiors", "eyebrow": "Solutions · Home & interiors",
        "h1": "The cushion buyer hiding a <em>whole-house project.</em>",
        "lede": "Interior designers, stylists, and trade buyers place orders that look ordinary and "
                "recur for years. A single accessory can be the front of a five-figure specification.",
        "problem_h2": "Small order, standing relationship.",
        "problem_p": "A designer testing your quality with one item looks like any retail shopper — but "
                     "they buy for clients, repeatedly, for years. Miss the tell and you hand a trade "
                     "relationship to a competitor over a one-off discount.",
        "low": "£60 accessory", "high": "£40k room specification",
        "case_line": "A £75 order, company billing, repeat delivery to a Chelsea address.",
        "case_reveal": "an interior designer sourcing for a client — a trade account worth years of "
                       "recurring orders, arriving as a small retail sale.",
        "surfaces": ["Company & trade billing", "Repeat delivery addresses", "Trophy addresses",
                     "Prime postcodes", "Wealth structures"],
        "move_h2": "Open a trade relationship, not a one-off discount.",
        "move_p": "Halia spots company billing, recurring addresses, and prime locations, so you can "
                  "offer terms and a dedicated contact — the difference between a single sale and a "
                  "multi-year account.",
        "pull": "",
    },
    {
        "slug": "gifting", "name": "Flowers, food & gifting", "eyebrow": "Solutions · Flowers, food & gifting",
        "h1": "The £50 standing order from a <em>Belgravia address.</em>",
        "lede": "In flowers, fine food, and gifting, the modest recurring purchase is often the "
                "wealthy one — and the small retail order frequently hides a corporate or event budget.",
        "problem_h2": "The small order is the tell, not the noise.",
        "problem_p": "A weekly bouquet, a monthly hamper — low tickets, high frequency, and a large "
                     "hidden ceiling in events, corporate gifting, and standing accounts. Frequency is "
                     "your friend: more orders per head, more signal, faster proof.",
        "low": "£50 weekly order", "high": "£4k event & corporate gifting",
        "case_line": "A £48 standing weekly delivery to SW1, placed by an assistant.",
        "case_reveal": "not a small customer — a household whose event and corporate budget you never "
                       "get asked about, because the retail order looks tiny.",
        "surfaces": ["Prime postcodes & residences", "Company billing", "Recurring delivery patterns",
                     "Premium email", "Assistant orders"],
        "move_h2": "Turn a standing order into a house account.",
        "move_p": "Halia flags the recurring, well-heeled, or PA-placed order and prompts a personal "
                  "outreach — the private account, the events conversation — before the budget goes "
                  "somewhere else.",
        "pull": "",
    },
    {
        "slug": "collectibles", "name": "Rare books & collectibles", "eyebrow": "Solutions · Rare books & collectibles",
        "h1": "£20 paperbacks and £8,000 first editions, <em>one till.</em>",
        "lede": "A serious collector buys everyday reading beside the rare piece. The trade knows this "
                "by instinct; nobody has systematised it.",
        "problem_h2": "The collector hides in plain sight.",
        "problem_p": "In rare books, prints, coins, and design objects, the base of modest purchases is "
                     "full of serious collectors quietly building. Any single order's value tells you "
                     "almost nothing about who is worth a catalogue call.",
        "low": "£20 reading copy", "high": "£8,000 first edition",
        "case_line": "A steady run of £20–£40 orders, a prime address, a bibliophile's own domain.",
        "case_reveal": "a collector you would want first on the catalogue — indistinguishable, today, "
                       "from a casual buyer.",
        "surfaces": ["Prime addresses", "Premium & custom domains", "Honorifics", "Wealth structures",
                     "Order frequency"],
        "move_h2": "Send the catalogue call to the real collector.",
        "move_p": "Halia ranks the quiet buyers most likely to be building a collection, so early "
                  "offers and catalogue previews reach them first — the systematised version of what "
                  "your best dealer already does on a hunch.",
        "pull": "",
    },
    {
        "slug": "electronics", "name": "Electronics & big-box", "eyebrow": "Solutions · Electronics & big-box",
        "h1": "In a book this big, the high-value buyer is <em>invisible.</em>",
        "lede": "High-street and big-box electronics move enormous volume at every price point. A £40 "
                "cable and a £4,000 home-cinema fit-out sit in the same database — and the "
                "multi-property or trade buyer is lost in it.",
        "problem_h2": "Volume is the disguise.",
        "problem_p": "When millions of orders span every wealth level, transaction value tells you "
                     "nothing about lifetime potential. The landlord kitting out ten flats, the studio "
                     "buying gear, the household mid-renovation all look like single small sales.",
        "low": "£40 accessory", "high": "£40k multi-property / trade fit-out",
        "case_line": "Three £40 orders to three different postcodes, one billing address.",
        "case_reveal": "a landlord or trade buyer furnishing multiple properties — a premium-account "
                       "prospect your checkout treats as three tiny, unrelated sales.",
        "surfaces": ["Multi-address patterns", "Company & trade billing", "Prime & multiple postcodes",
                     "Premium cards", "Repeat behaviour"],
        "move_h2": "Feed your premium arm the leads it can't see.",
        "move_p": "Here Halia is lead qualification for your business / premium division — surfacing "
                  "the trade, landlord, and high-ceiling households hiding in retail volume, so a human "
                  "account team can reach them. The engine is the same; the buyer on your side is a "
                  "premium-account function rather than a clienteling desk.",
        "pull": "",
    },
]

_CSS = """
  :root{--bg:#f5f2ea;--bg-2:#efeadd;--ink:#1a1712;--mute:#615b50;--faint:#9a9385;--gold:#7a7363;
    --line:rgba(20,18,12,.14);--line-2:rgba(20,18,12,.07);
    --serif:'Cormorant Garamond',Georgia,serif;--sans:'Inter',-apple-system,system-ui,sans-serif}
  *{box-sizing:border-box}html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:hidden}
  a{color:inherit;text-decoration:none}::selection{background:#1a1712;color:#f5f2ea}
  .wrap{max-width:1180px;margin:0 auto;padding:0 40px}.narrow{max-width:820px}
  .eyebrow{font:500 12px/1 var(--sans);letter-spacing:.32em;text-transform:uppercase;color:var(--gold)}
  h1,h2,h3{font-family:var(--serif);font-weight:300;letter-spacing:-.01em;margin:0;line-height:1.04}
  .display{font-size:clamp(44px,7vw,88px)}.h2{font-size:clamp(30px,4.4vw,52px)}
  em{font-style:italic;color:var(--gold)}
  .lede{font-size:clamp(18px,2vw,22px);color:var(--mute);line-height:1.5}
  .btn{display:inline-flex;align-items:center;gap:10px;font:500 14px var(--sans);padding:14px 26px;border-radius:999px;border:1px solid var(--ink);color:#f5f2ea;background:var(--ink);transition:.25s;cursor:pointer}
  .btn:hover{background:transparent;color:var(--ink)}.btn.ghost{background:transparent;color:var(--ink);border-color:var(--line)}.btn.ghost:hover{border-color:var(--ink)}
  .arrow{transition:transform .25s}.btn:hover .arrow{transform:translateX(4px)}
  header{position:fixed;inset:0 0 auto;z-index:40;transition:.3s}header.solid{background:rgba(245,242,234,.82);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
  .nav{display:flex;align-items:center;justify-content:space-between;height:78px}
  .brand{display:flex;align-items:center;gap:11px;font-family:var(--serif);font-size:26px}
  .nav-links{display:flex;gap:32px}.nav-links a{font:500 14px var(--sans);color:var(--mute)}.nav-links a:hover{color:var(--ink)}
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
  .reveal{opacity:0;transform:translateY(26px);transition:opacity 1s cubic-bezier(.2,.6,.2,1),transform 1s cubic-bezier(.2,.6,.2,1)}.reveal.in{opacity:1;transform:none}.reveal.d1{transition-delay:.1s}
  @media(prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none}}
  .ip-hero{padding:168px 0 24px}.ip-hero h1{margin:16px 0 24px;max-width:20ch}.ip-hero .lede{max-width:60ch}
  .ipsec{padding:clamp(58px,8vh,104px) 0;border-top:1px solid var(--line-2)}
  .ipsec h2{margin-bottom:18px;max-width:24ch}.ipsec p{color:var(--mute);font-size:17px;max-width:60ch}
  .contrast{display:flex;flex-wrap:wrap;margin-top:34px;border:1px solid var(--line);border-radius:16px;overflow:hidden}
  .contrast > div{flex:1 1 260px;padding:28px 30px}
  .contrast .hi{background:var(--ink);color:var(--bg)}
  .contrast .k{font:500 11px var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin-bottom:10px}
  .contrast .hi .k{color:rgba(245,242,234,.6)}
  .contrast .v{font-family:var(--serif);font-size:clamp(24px,3.2vw,34px);line-height:1.08}
  .contrast .same{flex:0 0 100%;padding:14px 30px;background:var(--bg-2);color:var(--faint);font-size:13.5px;border-top:1px solid var(--line)}
  .case{border:1px solid var(--gold);border-radius:18px;padding:clamp(28px,4vw,40px);background:var(--bg-2)}
  .case .lab{font:500 11px var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--gold);margin-bottom:16px}
  .case .line{font-family:var(--serif);font-size:clamp(22px,3vw,32px);line-height:1.15;margin-bottom:16px}
  .case .rv{color:var(--mute);font-size:16.5px}.case .rv b{color:var(--ink);font-weight:600}
  .surfaces .sl{font:500 11px var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin:26px 0 14px}
  .tags{display:flex;flex-wrap:wrap;gap:9px}.tag{font:500 13px var(--sans);color:var(--mute);border:1px solid var(--line);padding:7px 13px;border-radius:999px}
  .pull{font-family:var(--serif);font-style:italic;font-size:clamp(22px,3.2vw,34px);line-height:1.2;color:var(--gold);max-width:26ch;margin-top:30px}
  .others .sl{font:500 11px var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--faint);margin-bottom:14px}
  .others .row{display:flex;flex-wrap:wrap;gap:10px}
  .others a{font:500 13.5px var(--sans);color:var(--mute);border:1px solid var(--line);padding:9px 15px;border-radius:999px}.others a:hover{border-color:var(--ink);color:var(--ink)}
  .final{text-align:center}.final h2{margin-bottom:18px}
  .pad{padding:clamp(80px,11vh,140px) 0}
  footer{border-top:1px solid var(--line);padding:60px 0 44px;margin-top:30px}
"""

_ASTER = "&#8258;"


def _nav() -> str:
    return (
        '<header id="hdr"><div class="wrap nav">'
        f'<a class="brand" href="/"><span aria-hidden="true" style="font-family:\'Cormorant Garamond\',Georgia,serif;font-size:22px;line-height:1;color:#d8d2c6">{_ASTER}</span>Halia</a>'
        '<nav class="nav-links"><a href="/#how">How it works</a><a href="/clienteling">Clienteling</a>'
        '<a href="/solutions">Solutions</a><a href="/pricing">Pricing</a><a href="/security">Security</a>'
        '<a href="/faq">FAQ</a></nav>'
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
    links = "".join(
        f'<a href="/solutions/{i["slug"]}">{i["name"]}</a>'
        for i in INDUSTRIES if i["slug"] != current)
    return ('<section class="ipsec"><div class="wrap reveal"><div class="others">'
            '<div class="sl">Halia by industry</div><div class="row">'
            f'<a href="/solutions">All solutions</a>{links}</div></div></div></section>')


def render(ind: dict) -> str:
    tags = "".join(f'<span class="tag">{t}</span>' for t in ind["surfaces"])
    pull = (f'<div class="pull reveal d1">&ldquo;{ind["pull"]}&rdquo;</div>' if ind["pull"] else "")
    body = f"""
<section class="ip-hero"><div class="wrap">
  <div class="eyebrow reveal in">{ind["eyebrow"]}</div>
  <h1 class="display reveal in d1">{ind["h1"]}</h1>
  <p class="lede reveal in d1">{ind["lede"]}</p>
</div></section>

<section class="ipsec"><div class="wrap">
  <div class="eyebrow reveal" style="margin-bottom:16px">The problem</div>
  <h2 class="h2 reveal">{ind["problem_h2"]}</h2>
  <p class="reveal d1" style="margin-top:16px">{ind["problem_p"]}</p>
  <div class="contrast reveal d1">
    <div><div class="k">Looks like</div><div class="v">{ind["low"]}</div></div>
    <div class="hi"><div class="k">Could be worth</div><div class="v">{ind["high"]}</div></div>
    <div class="same">Same transaction. Different client. Spend alone can't tell them apart &mdash; Halia can.</div>
  </div>
</div></section>

<section class="stmt-sec"><div class="wrap">
  <p class="stmt reveal">Transaction value is a bad proxy for customer <em>value.</em></p>
</div></section>

<section class="ipsec"><div class="wrap narrow">
  <div class="case reveal">
    <div class="lab">A client you can't see</div>
    <div class="line">{ind["case_line"]}</div>
    <div class="rv"><b>What's really going on:</b> {ind["case_reveal"]}</div>
  </div>
</div></section>

<section class="ipsec"><div class="wrap">
  <div class="eyebrow reveal" style="margin-bottom:16px">What Halia surfaces</div>
  <h2 class="h2 reveal">The tells behind {ind["name"].split(" &amp; ")[0].split(", ")[0].lower()} orders.</h2>
  <div class="surfaces reveal d1"><div class="sl">Read from data you already hold</div>{'<div class="tags">' + tags + '</div>'}</div>
</div></section>

<section class="ipsec"><div class="wrap">
  <div class="eyebrow reveal" style="margin-bottom:16px">The move</div>
  <h2 class="h2 reveal">{ind["move_h2"]}</h2>
  <p class="reveal d1" style="margin-top:16px">{ind["move_p"]}</p>
  {pull}
</div></section>

{_others(ind["slug"])}

<section class="pad final"><div class="wrap reveal">
  <div class="eyebrow" style="margin-bottom:24px">Begin</div>
  <h2 class="h2">See who you have been missing.</h2>
  <p class="lede" style="max-width:36ch;margin:16px auto 34px">Connect your store and Halia surfaces your hidden VICs, usually within the hour.</p>
  <a class="btn" href="/connect">Connect your store <span class="arrow">&rarr;</span></a>
</div></section>
"""
    return (
        "<!doctype html><html lang=\"en\"><head>"
        "<link rel=\"stylesheet\" href=\"/static/brand.css\"><script src=\"/static/brand.js\" defer></script>"
        f"<link rel=\"icon\" href=\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text x='16' y='16' font-family='Georgia,serif' font-size='30' text-anchor='middle' dominant-baseline='central' fill='%237a7363'>{_ASTER}</text></svg>\">"
        "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{ind['name']} · Halia</title>"
        f"<meta name=\"description\" content=\"Halia for {ind['name'].lower()}: find the high-value clients hiding in a book full of low-ticket orders, and the move to act on them.\">"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
        "<link href=\"https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300;1,400&family=Inter:wght@400;500&display=swap\" rel=\"stylesheet\">"
        f"<style>{_CSS}</style></head><body>"
        f"{_nav()}{body}{_footer()}{_SCRIPT}</body></html>"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ind in INDUSTRIES:
        (OUT / f"{ind['slug']}.html").write_text(render(ind), encoding="utf-8")
    print(f"Wrote {len(INDUSTRIES)} industry pages to {OUT}:", file=sys.stderr)
    for ind in INDUSTRIES:
        print(f"  /solutions/{ind['slug']}  ({ind['name']})", file=sys.stderr)


if __name__ == "__main__":
    main()
