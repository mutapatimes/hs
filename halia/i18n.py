"""What a client reads, in the store's own language.

The first localisation layer this codebase has had. It exists for the pages a CLIENT lands on
(the selection page, the appointment invite, the capture form) and the enquiry mail the team
receives; the merchant dashboard stays English. The language is the one the store already chose
for its house voice (settings.voice.language), so there is one idea of what language a store
speaks, not two switches to keep aligned.

Usage: ``t(lang, key, **fmt)``. Unknown language or key falls back to English, so a missing
translation degrades to what every page said before this module existed.

Japanese notes: the copy below is drafted in polite keigo suitable for a luxury boutique and is
MARKED FOR NATIVE REVIEW before a Japanese merchant sees it. Dates render as 9月14日（土）rather
than "Saturday 14 September" (no locale dependency, so it works on any host).
"""
from __future__ import annotations

from datetime import datetime

# Languages with real page translations. Anything else renders English.
PAGE_LANGS = ("en", "ja")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # ── the selection page (halia/catalog_form.py) ──
        "cat.title_fallback": "Product Catalogue",
        "cat.site_fallback": "Catalogue",
        "cat.lead": "Tick the pieces you would like, then send.",
        "cat.empty": "This catalogue has no products yet.",
        "cat.pick": "Pick",
        "cat.picked": "Picked",
        "cat.selected": "selected",
        "cat.clear": "Clear",
        "cat.continue": "Continue",
        "cat.sheet_title": "Your details",
        "cat.name": "Your name",
        "cat.name_ph": "Full name",
        "cat.email": "Email",
        "cat.phone": "Phone (optional)",
        "cat.phone_ph": "Optional",
        "cat.message": "Message (optional)",
        "cat.message_ph": "Anything else?",
        "cat.back": "Back",
        "cat.send": "Send my picks",
        "cat.err_need": "Please add your name and email.",
        "cat.sending": "Sending…",
        "cat.err_send": "Could not send",
        "cat.sent": "Sent",
        "cat.thanks": "Thank you. They have your picks and will be in touch shortly.",
        "cat.picked_n": "Picked {n} piece{s}:",
        "cat.none_yet": "No items selected yet.",
        "cat.adhoc_title": "A selection for {first_name}",
        "cat.og_for": "A selection for {first} · {pieces}",
        "cat.og_pieces": "{pieces} chosen for you",
        "cat.piece_one": "{n} piece",
        "cat.piece_many": "{n} pieces",
        # ── the appointment invite (halia/api/appointments.py) ──
        "appt.add": "Add to my calendar",
        "appt.google": "Google Calendar",
        "appt.outlook": "Outlook",
        "appt.title_at": "Appointment at {store}",
        "appt.title": "Appointment",
        "appt.message": "Your appointment is set for {when}{where}. Add it to your calendar here: {url}",
        "appt.message_at": " at {place}",
        # ── the capture form (halia/api/capture.py) ──
        "cap.lead": "Leave your details and we’ll look after you.",
        "cap.first": "First name",
        "cap.last": "Last name",
        "cap.furigana": "Name reading",
        "cap.phone": "Phone",
        "cap.email": "Email",
        "cap.birthday": "Birthday",
        "cap.birthday_why": "for a birthday treat",
        "cap.birthday_ph": "14 June",
        "cap.address": "Delivery address",
        "cap.address_why": "for gifts, deliveries and event invitations",
        "cap.street_ph": "Street address",
        "cap.postcode_ph": "Postcode",
        "cap.city_ph": "City",
        "cap.prefs": "Sizes, likes, occasions (optional)",
        "cap.consent_email": "Email me about new arrivals and events",
        "cap.consent_sms": "Text me occasionally",
        "cap.foot": "Kept by {store} for personal service.",
        "cap.save": "Save my details",
        "cap.saving": "Saving…",
        "cap.need_one": "A phone number or email is needed.",
        "cap.did_you_mean": "Did you mean {suggestion}?",
        "cap.thanks": "Thank you",
        "cap.good_hands": "You are in good hands.",
        # ── the enquiry mail to the team (halia/api/catalog.py) ──
        "enq.subject": "{name} picked {pieces}",
        "enq.lead": "{name} picked {n} of the pieces you sent.",
        "enq.new_from": "New enquiry from {name} via your {cat} catalogue.",
        "enq.product": "Product",
        "enq.price": "Price",
        "enq.none": "(No specific products ticked)",
        "enq.message": "Message",
        "enq.reply": "Sent to you by Halia. Reply directly to {email} to respond.",
    },
    # ═══ 日本語 — drafted by Halia in polite keigo; AWAITING NATIVE REVIEW. Do not show to a
    #     Japanese merchant as finished copy until a native speaker has passed it. ═══
    "ja": {
        "cat.title_fallback": "商品カタログ",
        "cat.site_fallback": "カタログ",
        "cat.lead": "気になるお品をお選びのうえ、送信してください。",
        "cat.empty": "商品は準備中です。",
        "cat.pick": "選ぶ",
        "cat.picked": "選択中",
        "cat.selected": "点選択中",
        "cat.clear": "クリア",
        "cat.continue": "次へ",
        "cat.sheet_title": "お客様情報",
        "cat.name": "お名前",
        "cat.name_ph": "姓名",
        "cat.email": "メールアドレス",
        "cat.phone": "お電話番号（任意）",
        "cat.phone_ph": "任意",
        "cat.message": "メッセージ（任意）",
        "cat.message_ph": "ご要望などございましたら",
        "cat.back": "戻る",
        "cat.send": "送信する",
        "cat.err_need": "お名前とメールアドレスをご入力ください。",
        "cat.sending": "送信中…",
        "cat.err_send": "送信できませんでした",
        "cat.sent": "送信しました",
        "cat.thanks": "ありがとうございます。担当者より折り返しご連絡いたします。",
        "cat.picked_n": "お選びいただいた{n}点{s}：",
        "cat.none_yet": "まだお品が選択されていません。",
        "cat.adhoc_title": "{first_name}様へのセレクション",
        "cat.og_for": "{first}様へのセレクション · {pieces}",
        "cat.og_pieces": "お客様のために選んだ{pieces}",
        "cat.piece_one": "{n}点",
        "cat.piece_many": "{n}点",
        "appt.add": "カレンダーに追加",
        "appt.google": "Googleカレンダー",
        "appt.outlook": "Outlook",
        "appt.title_at": "{store} ご予約",
        "appt.title": "ご予約",
        "appt.message": "{when}{where}にてご予約を承りました。カレンダーへのご登録はこちらから：{url}",
        "appt.message_at": "、{place}",
        "cap.lead": "お客様情報をご登録いただけましたら、心を込めてご案内いたします。",
        "cap.first": "名",
        "cap.last": "姓",
        "cap.furigana": "フリガナ",
        "cap.phone": "お電話番号",
        "cap.email": "メールアドレス",
        "cap.birthday": "お誕生日",
        "cap.birthday_why": "バースデーのご案内のため",
        "cap.birthday_ph": "6月14日",
        "cap.address": "お届け先ご住所",
        "cap.address_why": "ギフトの発送やイベントのご案内のため",
        "cap.street_ph": "市区町村・番地・建物名",
        "cap.postcode_ph": "郵便番号",
        "cap.city_ph": "都道府県",
        "cap.prefs": "サイズ・お好み・記念日など（任意）",
        "cap.consent_email": "新作やイベントのご案内をメールで受け取る",
        "cap.consent_sms": "SMSでのご案内を受け取る",
        "cap.foot": "ご記入いただいた情報は、{store}がお客様へのご案内のためにお預かりいたします。",
        "cap.save": "登録する",
        "cap.saving": "送信中…",
        "cap.need_one": "お電話番号またはメールアドレスをご入力ください。",
        "cap.did_you_mean": "もしかして {suggestion} ではありませんか？",
        "cap.thanks": "ありがとうございます",
        "cap.good_hands": "担当者より心を込めてご案内いたします。",
        "enq.subject": "{name}様が{pieces}をお選びになりました",
        "enq.lead": "お送りしたセレクションから、{name}様が{n}点をお選びになりました。",
        "enq.new_from": "{cat}カタログより、{name}様からお問い合わせをいただきました。",
        "enq.product": "商品",
        "enq.price": "価格",
        "enq.none": "（商品の指定はありません）",
        "enq.message": "メッセージ",
        "enq.reply": "Haliaよりお届けしています。ご返信は {email} へ直接どうぞ。",
    },
}


def clean_lang(raw) -> str:
    lang = str(raw or "").strip().lower()[:5]
    return lang if lang in PAGE_LANGS else "en"


def t(lang: str, key: str, **fmt) -> str:
    """The string a client reads. Missing translations fall back to English rather than to a
    blank or a KeyError, so an untranslated page is exactly the page we shipped before."""
    lang = clean_lang(lang)
    text = STRINGS.get(lang, {}).get(key) or STRINGS["en"].get(key) or key
    try:
        return text.format(**fmt) if fmt else text
    except (KeyError, IndexError):
        return text


def client_lang(shop: str) -> str:
    """The language this store's clients read: the same one the house voice writes in. One idea
    of what language a store speaks, not a second switch to keep aligned."""
    try:
        from halia.api.settings import settings_for
        return clean_lang(((settings_for(shop) or {}).get("voice") or {}).get("language"))
    except Exception:  # noqa: BLE001 — a settings hiccup must never blank a client page
        return "en"


def pieces(lang: str, n: int) -> str:
    """"3 pieces" / "3点"."""
    return t(lang, "cat.piece_one" if n == 1 else "cat.piece_many", n=n)


_JA_DOW = "月火水木金土日"


def date_words(dt: datetime, lang: str) -> str:
    """"Saturday 14 September" / "9月14日（土）"."""
    if clean_lang(lang) == "ja":
        return f"{dt.month}月{dt.day}日（{_JA_DOW[dt.weekday()]}）"
    return dt.strftime("%A %-d %B") if _dash_ok() else dt.strftime("%A %d %B").replace(" 0", " ")


def when_words(dt: datetime, lang: str) -> str:
    """"Saturday 14 September at 15:00" / "9月14日（土）15:00"."""
    hm = dt.strftime("%H:%M")
    if clean_lang(lang) == "ja":
        return f"{date_words(dt, lang)}{hm}"
    return f"{date_words(dt, lang)} at {hm}"


def _dash_ok() -> bool:
    """%-d is glibc/mac only; fall back to stripping the leading zero elsewhere."""
    try:
        datetime(2026, 1, 2).strftime("%-d")
        return True
    except ValueError:
        return False


def html_lang(lang: str) -> str:
    return clean_lang(lang)


def font_prefix(lang: str) -> str:
    """Faces to put in front of the page's stack when the language needs them."""
    return '"Hiragino Sans","Yu Gothic",Meiryo,' if clean_lang(lang) == "ja" else ""
