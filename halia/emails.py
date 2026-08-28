"""Branded HTML for Halia's lifecycle emails (demo nurture, client welcome, weekly nudges).

Each template is a small function returning ``(subject, body_html, body_text)``. ``render()`` wraps
the body in a shared, email-client-safe layout (table-based, inline styles, web-safe fonts, the ⁂
wordmark, and an unsubscribe footer). Copy follows the brand voice: no em dashes, positive framing.

The journey engine (halia/journeys.py) owns timing, suppression, and sending via halia.notify.
"""
from __future__ import annotations

import html as _html

from halia import config

# Brand tokens (kept inline-safe; no external CSS/fonts for deliverability).
_CREAM = "#f4f1ea"
_PAPER = "#ffffff"
_INK = "#1a1712"
_MUT = "#6b675e"
_FAINT = "#9a9488"
_ACCENT = "#1f564a"     # brand green
_ACCENT_DK = "#143a32"
_LINE = "#e7e1d4"
_SERIF = "Georgia, 'Times New Roman', serif"
_SANS = "Helvetica, Arial, sans-serif"


def base_url() -> str:
    return (config.HALIA_APP_URL or "https://haliascore.com").rstrip("/")


def _btn(label: str, href: str) -> str:
    return (
        f"<table role=presentation cellpadding=0 cellspacing=0 style='margin:26px 0 10px'><tr><td "
        f"style='border-radius:0;background:{_ACCENT}'>"
        f"<a href='{href}' style='display:inline-block;padding:14px 30px;font:600 14px {_SANS};"
        f"letter-spacing:.03em;color:#ffffff;text-decoration:none;border-radius:0'>"
        f"{_html.escape(label)} &#8594;</a>"
        f"</td></tr></table>")


def _p(text: str) -> str:
    return f"<p style='margin:0 0 16px;font:16px/1.65 {_SANS};color:{_INK}'>{text}</p>"


# Per-journey eyebrow shown in the masthead hero (keyed by the template prefix).
_EYEBROW = {
    "demo": "An introduction",
    "client": "Welcome to Halia",
    "weekly": "Your week with Halia",
    "assoc": "Your Halia seat",
    "monthly": "Your month with Halia",
}


def _hero(eyebrow: str) -> str:
    """A self-composed, image-free masthead hero: the mark, the wordmark, a hairline.

    No external image on purpose — it renders identically in every client, carries no deliverability
    weight, and cannot break before the domain is serving. The ``eyebrow`` text is no longer painted
    here (kicker labels read as filler); it survives only as the hidden inbox preheader in _layout.
    """
    return (
        f"<tr><td align=center style='padding:8px 0 30px'>"
        # the asterism mark, in brand green
        f"<div style='font:400 30px {_SERIF};color:{_ACCENT};line-height:1'>&#8258;</div>"
        # wordmark
        f"<div style='font:300 32px {_SERIF};color:{_INK};letter-spacing:.05em;margin-top:9px'>Halia</div>"
        # hairline
        f"<div style='width:34px;height:2px;background:{_ACCENT};margin:18px auto 2px'></div>"
        f"</td></tr>")


def _layout(subject: str, greeting: str, body_html: str, unsub_url: str, eyebrow: str) -> str:
    """Wrap a body in the shared shell. ``body_html`` is pre-built paragraphs/buttons."""
    year = "2026"
    return (
        f"<!doctype html><html><head><meta charset=utf-8>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<meta name=color-scheme content='light'><title>{_html.escape(subject)}</title></head>"
        f"<body style='margin:0;padding:0;background:{_CREAM};"
        f"-webkit-font-smoothing:antialiased'>"
        # preheader (hidden): the eyebrow, so the inbox preview reads on-brand
        f"<div style='display:none;max-height:0;overflow:hidden;opacity:0'>{_html.escape(eyebrow)} &#8226; Halia</div>"
        f"<table role=presentation width=100% cellpadding=0 cellspacing=0 style='background:{_CREAM}'>"
        f"<tr><td align=center style='padding:38px 16px 30px'>"
        f"<table role=presentation width=568 cellpadding=0 cellspacing=0 "
        f"style='max-width:568px;width:100%'>"
        # masthead hero
        f"{_hero(eyebrow)}"
        f"<tr><td style='background:{_PAPER};border:1px solid {_LINE};border-top:none;"
        f"border-radius:0;padding:36px 38px 30px'>"
        f"<p style='margin:0 0 20px;font:600 17px/1.5 {_SERIF};color:{_INK}'>{greeting}</p>"
        f"{body_html}"
        # sign-off
        f"<p style='margin:26px 0 0;font:italic 15px/1.6 {_SERIF};color:{_MUT}'>"
        f"With care,<br>The Halia team</p>"
        f"</td></tr>"
        # footer
        f"<tr><td align=center style='padding:26px 8px 4px'>"
        f"<div style='font:400 15px {_SERIF};color:{_ACCENT}'>&#8258;</div>"
        f"<p style='margin:8px 0 0;font:11px/1.7 {_SANS};letter-spacing:.02em;color:{_MUT}'>"
        f"Private client intelligence for luxury retail<br>"
        f"<a href='{base_url()}' style='color:{_ACCENT};text-decoration:none'>haliascore.com</a></p>"
        + (  # unsub line only on marketing emails; transactional ones (unsub_url="") omit it
            f"<p style='margin:12px 0 0;font:11px/1.7 {_SANS};color:{_FAINT}'>"
            f"You are receiving this because you asked about Halia or use it. "
            f"<a href='{unsub_url}' style='color:{_FAINT};text-decoration:underline'>Unsubscribe</a>"
            f" &middot; &copy; {year} Midnight Lantern Technologies Ltd</p>"
            if unsub_url else
            f"<p style='margin:12px 0 0;font:11px/1.7 {_SANS};color:{_FAINT}'>"
            f"&copy; {year} Midnight Lantern Technologies Ltd</p>")
        + f"</td></tr></table></td></tr></table></body></html>")


def _greeting(d: dict) -> str:
    first = str(d.get("first") or "").strip()
    return f"Hello {_html.escape(first)}," if first else "Hello,"


def _app(d: dict) -> str:
    return d.get("app") or base_url()


# ── demo nurture ─────────────────────────────────────────────────────────────────
def demo_intro(d):
    body = (
        _p("Thank you for asking to see Halia. A member of our team will be in touch shortly to "
           "arrange a time that suits you.")
        + _p("In the meantime, the short version: Halia reads the order data you already hold and "
             "surfaces the customers who behave like your very best clients but were never tagged "
             "as such. Your hidden VICs.")
        + _p("We look forward to showing you your own."))
    return ("We'll be in touch about your Halia demo", body,
            "Thank you for asking to see Halia. A member of our team will be in touch shortly to "
            "arrange your demo. Halia surfaces the customers who behave like your best clients but "
            "were never tagged as such. We look forward to showing you your own.")


def demo_hidden(d):
    body = (
        _p("Most luxury retailers can name their top thirty clients. Halia finds the next hundred.")
        + _p("It scores every customer across dozens of quiet signals of wealth and intent, from "
             "the neighbourhood they ship to, to the cadence of their spend, and ranks the ones "
             "worth a personal word.")
        + _p("Reply to this email and we will run a sample on your store."))
    return ("The clients you already have, hiding in plain sight", body,
            "Most retailers can name their top thirty clients. Halia finds the next hundred, scored "
            "across dozens of signals of wealth and intent. Reply and we will run a sample on your store.")


def demo_how(d):
    body = (
        _p("Every grade comes with its reasons in plain English, so your team trusts the call.")
        + _p("And it is built to be quiet. Customers are scored in memory and discarded. Nothing "
             "about them is stored or shared. Intelligence you can act on, held to the standard "
             "your clients expect.")
        + _btn("See the approach", f"{_app(d)}/security"))
    return ("How Halia scores, and why it is safe", body,
            "Every grade comes with its reasons in plain English. Customers are scored in memory and "
            "discarded, nothing stored or shared. See the approach: " + f"{_app(d)}/security")


def demo_ready(d):
    body = (
        _p("Whenever you would like to see Halia on your own customers, we can have you connected "
           "in a few minutes.")
        + _btn("Connect your store", f"{_app(d)}/connect")
        + _p("Or simply reply to this email and we will take care of it with you."))
    return ("Ready when you are", body,
            "Whenever you would like to see Halia on your own customers, connect in a few minutes: "
            f"{_app(d)}/connect . Or reply and we will take care of it with you.")


# ── client welcome ───────────────────────────────────────────────────────────────
def client_welcome(d):
    body = (
        _p("Welcome. Halia is now reading your orders and grading your customers, so the people "
           "worth a personal touch rise to the top.")
        + _p("Your first step: open your dashboard and look at your hidden VICs, sorted by grade, "
             "each with the reasons behind it.")
        + _btn("Open your dashboard", f"{_app(d)}/app")
        + _p("We are here whenever you need us. Simply reply to this email."))
    return ("Welcome to Halia", body,
            "Welcome. Halia is grading your customers so the people worth a personal touch rise to "
            f"the top. Open your dashboard: {_app(d)}/app . Reply any time, we read everything.")


def client_action(d):
    body = (
        _p("A grade is only useful when it becomes a gesture.")
        + _p("From your dashboard you can send a ready template, sync a client to Klaviyo or "
             "Mailchimp with their grade, or flag them at the till. Pick one hidden VIC this week "
             "and reach out.")
        + _btn("Action a hidden VIC", f"{_app(d)}/app")
        + _p("If you would like a hand, reply and we will walk through it with you."))
    return ("Turn a hidden VIC into a moment", body,
            "A grade is only useful when it becomes a gesture. Send a template, sync to Klaviyo or "
            f"Mailchimp, or flag them at the till. Action one this week: {_app(d)}/app")


def client_feedback(d):
    body = (
        _p("Beside every client in Halia is a small good call, or not a fit.")
        + _p("Those two taps are the most valuable thing you can give Halia. Each one tunes the "
             "weights to your business, so the grades get more precise the more you use them.")
        + _p("It costs a second, and it compounds in your favour."))
    return ("Good call, bad call: the habit that sharpens Halia", body,
            "Beside every client is a small good call / not a fit. Those taps tune Halia to your "
            "business so your grades get more precise. It costs a second and compounds in your favour.")


# ── recurring weekly nudge (rotates) ─────────────────────────────────────────────
def weekly_vics(d):
    hidden = d.get("hidden")
    lead = (f"You surfaced {int(hidden)} hidden VICs recently. Have they had a personal word yet?"
            if hidden else
            "New orders mean new customers to grade, and there may be hidden VICs among them.")
    body = (
        _p("A quiet reminder to check Halia this week.")
        + _p(_html.escape(lead))
        + _btn("Check for new VICs", f"{_app(d)}/app")
        + _p("Make the most of the clients you already have."))
    return ("New potential VICs are waiting on Halia", body,
            "A quiet reminder to check Halia this week. " + lead + f" {_app(d)}/app")


def weekly_team(d):
    t = (d.get("team") or {}).get("totals") or {}
    top = (d.get("team") or {}).get("top") or []
    money = lambda n: "£" + f"{int(n or 0):,}"
    lead = (f"Last week your team logged {int(t.get('contacts') or 0)} contacts with "
            f"{int(t.get('clients') or 0)} clients, captured {int(t.get('captures') or 0)} new ones, and "
            f"{int(t.get('conversions') or 0)} of those contacts led to an order: {money(t.get('revenue'))}.")
    names = "; ".join(f"{_html.escape(r.get('name',''))}: {money(r.get('revenue'))} from "
                      f"{int(r.get('contacts') or 0)} contact{'s' if r.get('contacts') != 1 else ''}"
                      for r in top)
    body = (_p(_html.escape(lead))
            + (_p("Leading the week: " + names + ".") if names else "")
            + _btn("See the team report", f"{_app(d)}/app")
            + _p("Switch on Team performance at the top of the Overview for the full table."))
    return ("Your team, last week", body,
            lead + (" Leading the week: " + names + "." if names else "") + f" {_app(d)}/app")


def weekly_feedback(d):
    body = (
        _p("If you have a moment in Halia this week, mark a few grades as good call or not a fit.")
        + _p("It is the single habit that improves your precision, and it only benefits you. The "
             "more you tell Halia, the better it reads your customers.")
        + _btn("Open Halia", f"{_app(d)}/app"))
    return ("One tap that makes your grades sharper", body,
            "Mark a few grades as good call or not a fit this week. It improves your precision and "
            f"only benefits you. {_app(d)}/app")


def weekly_refresh(d):
    body = (
        _p("Templates go stale.")
        + _p("Take a minute in Halia to revisit your outreach, retire the lines that stopped "
             "landing, and lean into what converted. Small, regular edits keep every message "
             "feeling personal.")
        + _btn("Refresh your templates", f"{_app(d)}/app")
        + _p("We are here if you would like a second pair of eyes. Just reply."))
    return ("Refresh your outreach, keep what works", body,
            "Take a minute to revisit your outreach in Halia, retire lines that stopped landing, and "
            f"lean into what converted. {_app(d)}/app")


# ── public helpers so transactional emails (sign-in, scores-ready) share the same look ──
def paragraph(text: str) -> str:
    """A branded body paragraph (caller escapes any user text)."""
    return _p(text)


def button(label: str, href: str) -> str:
    """A branded call-to-action button."""
    return _btn(label, href)


def wrap(subject: str, body_html: str, *, greeting: str = "Hello,",
         eyebrow: str = "Halia", unsub_url: str = "") -> str:
    """Wrap pre-built body HTML in the shared branded shell. Pass unsub_url only for marketing
    emails; leave it empty for transactional ones (sign-in link, scores ready) to omit unsubscribe."""
    return _layout(subject, greeting, body_html, unsub_url, eyebrow)




def render(template_key: str, data: dict, unsub_url: str) -> tuple[str, str, str]:
    """Return (subject, html, text) for a template, wrapped in the shared branded layout."""
    builder = _TEMPLATES[template_key]
    subject, body_html, body_text = builder(data or {})
    eyebrow = _EYEBROW.get(template_key.split("_", 1)[0], "Halia")
    html = _layout(subject, _greeting(data or {}), body_html, unsub_url, eyebrow)
    return subject, html, body_text


# ── associate onboarding (a teammate given a seat) ─────────────────────────────
def _store(d: dict) -> str:
    return _html.escape(str(d.get("store_name") or "your store"))


def assoc_welcome(d):
    connect = str(d.get("connect") or "")
    body = (
        _p(f"You have a seat on Halia at {_store(d)}. Halia shows you who a client is, why they "
           "matter, and what to say next, wherever you talk to clients.")
        + _p("Two things to set up, five minutes in all:")
        + _p("<b>On your iPhone</b>: install the Halia app from the App Store, then tap the link "
             "below on your phone to sign in. Turn on the Halia keyboard in Settings, so client "
             "context and your templates are one tap away in WhatsApp and Messages.")
        + _p("<b>On your computer</b>: add the Halia extension to Chrome and sign in with the same "
             "link. It appears beside WhatsApp Web, Gmail and your store admin.")
        + (_btn("Sign in to Halia", connect) if connect else "")
        + _p("Keep this email: the link is yours alone and signs you in on any device."))
    return (f"Your Halia seat at {_store(d)}", body,
            f"You have a seat on Halia at {d.get('store_name') or 'your store'}. Install the Halia "
            f"app on your iPhone and the Chrome extension on your computer, then sign in with your "
            f"link: {connect}")


def assoc_first_moves(d):
    body = (
        _p("The first thing to try: open a client, anywhere. In WhatsApp Web or Gmail the Halia "
           "card appears in the corner with their grade, why they surfaced, and a note ready to send.")
        + _p("On the keyboard, tap the Halia key in any chat to look someone up by name, email or "
             "number, and drop in a template or a drafted reply in the house voice.")
        + _p("Grades run from A&#42; to C. An A&#42; is a client who deserves your best; a C is "
             "someone to serve well and move on. The reasons are always listed, so you can trust them.")
        + _btn("Open Halia", _app(d)))
    return ("Your first moves in Halia", body,
            "Open a client anywhere: the Halia card shows their grade, why, and a note ready to send. "
            "On the keyboard, tap the Halia key to look someone up and drop in a template.")


def assoc_capture(d):
    body = (
        _p("Clients you meet at the counter are the ones most tools never capture. In the Halia app, "
           "tap <b>Add a client</b>, hand over your phone, and they leave their details themselves: "
           "email, phone, birthday, the delivery address for gifts and invitations.")
        + _p("It lands straight in the store's customer book, typo-checked, and graded on the spot. "
             "Capture tools also give you a QR for the till and a WhatsApp code: the client scans, "
             "you have their number.")
        + _p("An address is the strongest signal you can capture. Ask for it as a delivery address; "
             "people give it gladly."))
    return ("Capture the clients you meet in store", body,
            "In the Halia app, tap Add a client and hand over your phone: their details land in the "
            "store's book, typo-checked and graded. Capture tools give you a till QR and a WhatsApp code.")


def assoc_habits(d):
    body = (
        _p("A rhythm that works: each morning, check <b>Reach today</b> for the clients worth a note. "
           "When a VIC order alert arrives, reply within the hour; it lands differently.")
        + _p("Before a client comes in, look them up so you greet them knowing what they love. After "
             "they leave, log the contact so the team knows who is looking after whom.")
        + _p("That is the whole job Halia does for you: the right client, the right moment, in your "
             "own voice."))
    return ("The weekly rhythm with Halia", body,
            "Each morning check Reach today; reply to VIC order alerts within the hour; look a client "
            "up before they come in; log the contact after.")


def monthly_seat(d):
    r = d.get("recap") or {}
    money = lambda n: "£" + f"{int(n or 0):,}"
    mn = _html.escape(str(r.get("month_name") or "last month"))
    store = _store(d)
    contacts, clients = int(r.get("contacts") or 0), int(r.get("clients") or 0)
    captures, conv, rev = int(r.get("captures") or 0), int(r.get("conversions") or 0), int(r.get("revenue") or 0)
    drafts, links, remembered = int(r.get("drafts") or 0), int(r.get("links") or 0), int(r.get("remembered") or 0)
    quiet = not any((contacts, captures, drafts, links, remembered))

    def row(label, value):
        return (f"<tr><td style='padding:9px 0;border-bottom:1px solid #E4E2DB;font:15px {_SERIF};color:{_INK}'>{label}</td>"
                f"<td align=right style='padding:9px 0;border-bottom:1px solid #E4E2DB;font:600 15px {_SERIF};color:{_INK}'>{value}</td></tr>")
    if quiet:
        body = (_p(f"{mn} was quiet on Halia. Two moves that take a minute each: look up the next client "
                   "who messages you, and capture one new client at the till.")
                + _btn("Open Halia", f"{_app(d)}/app"))
        text = f"{r.get('month_name') or 'Last month'} was quiet on Halia. Look up the next client who messages you, and capture one new client at the till. {_app(d)}/app"
        return (f"Your {r.get('month_name') or 'month'} with Halia at {d.get('store_name') or 'the store'}", body, text)

    lead = (f"In {mn} you reached {contacts} contact{'s' if contacts != 1 else ''} with {clients} client"
            f"{'s' if clients != 1 else ''}"
            + (f", captured {captures} new" if captures else "")
            + (f", and {conv} of your contacts led to an order: {money(rev)}." if conv else "."))
    table = ("<table role=presentation width=100% cellpadding=0 cellspacing=0 style='margin:6px 0 18px'>"
             + row("Contacts logged", contacts) + row("Clients reached", clients)
             + (row("Top-grade share", f"{int(round(float(r.get('top_share') or 0) * 100))}%") if clients else "")
             + row("Clients captured", captures)
             + row("Messages drafted with Halia", drafts) + row("Catalogue and basket links sent", links)
             + (row("Details remembered", remembered) if remembered else "")
             + row("Orders after a contact", conv) + row("Revenue credited", money(rev))
             + "</table>")
    rank, size = r.get("rank"), int(r.get("team_size") or 0)
    standing = (_p(f"You were number {rank} of {size} on the team at {store}.") if rank and size > 1 else "")
    body = _p(_html.escape(lead)) + table + standing + _btn("Open Halia", f"{_app(d)}/app")
    text = (lead + f" Drafted with Halia: {drafts}. Links sent: {links}."
            + (f" Number {rank} of {size} on the team." if rank and size > 1 else "") + f" {_app(d)}/app")
    return (f"Your {r.get('month_name') or 'month'} with Halia at {d.get('store_name') or 'the store'}", body, text)


_TEMPLATES = {
    "demo_intro": demo_intro, "demo_hidden": demo_hidden, "demo_how": demo_how,
    "demo_ready": demo_ready,
    "client_welcome": client_welcome, "client_action": client_action,
    "client_feedback": client_feedback,
    "weekly_vics": weekly_vics, "weekly_team": weekly_team, "weekly_feedback": weekly_feedback,
    "weekly_refresh": weekly_refresh,
    "assoc_welcome": assoc_welcome, "assoc_first_moves": assoc_first_moves,
    "assoc_capture": assoc_capture, "assoc_habits": assoc_habits,
    "monthly_seat": monthly_seat,
}
