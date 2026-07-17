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
_GOLD = "#a67c34"       # secondary accent, used with restraint
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
}


def _hero(eyebrow: str) -> str:
    """A self-composed, image-free masthead hero: the mark, wordmark, a hairline, and an eyebrow.

    No external image on purpose — it renders identically in every client, carries no deliverability
    weight, and cannot break before the domain is serving. A hosted banner can layer on later.
    """
    return (
        f"<tr><td align=center style='padding:8px 0 30px'>"
        # the asterism mark, in gold — the quiet brand tell
        f"<div style='font:400 30px {_SERIF};color:{_GOLD};line-height:1'>&#8258;</div>"
        # wordmark
        f"<div style='font:300 32px {_SERIF};color:{_INK};letter-spacing:.05em;margin-top:9px'>Halia</div>"
        # gold hairline
        f"<div style='width:34px;height:2px;background:{_GOLD};margin:18px auto 14px'></div>"
        # eyebrow
        f"<div style='font:600 11px {_SANS};letter-spacing:.26em;text-transform:uppercase;"
        f"color:{_MUT}'>{_html.escape(eyebrow)}</div>"
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
        # card — a fine gold top rule, then the white body
        f"<tr><td style='height:3px;background:{_GOLD};border-radius:0;"
        f"line-height:3px;font-size:0'>&nbsp;</td></tr>"
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
        f"<div style='font:400 15px {_SERIF};color:{_GOLD}'>&#8258;</div>"
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


_TEMPLATES = {
    "demo_intro": demo_intro, "demo_hidden": demo_hidden, "demo_how": demo_how,
    "demo_ready": demo_ready,
    "client_welcome": client_welcome, "client_action": client_action,
    "client_feedback": client_feedback,
    "weekly_vics": weekly_vics, "weekly_feedback": weekly_feedback,
    "weekly_refresh": weekly_refresh,
}


def render(template_key: str, data: dict, unsub_url: str) -> tuple[str, str, str]:
    """Return (subject, html, text) for a template, wrapped in the shared branded layout."""
    builder = _TEMPLATES[template_key]
    subject, body_html, body_text = builder(data or {})
    eyebrow = _EYEBROW.get(template_key.split("_", 1)[0], "Halia")
    html = _layout(subject, _greeting(data or {}), body_html, unsub_url, eyebrow)
    return subject, html, body_text
