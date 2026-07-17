"""Store Concierge messaging: template fill, channel links, stage/status suggestions."""
from halia.storeconcierge import messaging as m


def test_fill_personalises_name_and_shop():
    body = m.fill("Hi {first_name}, from {shop}", "Grace Ladoja", "Maison Aurelle")
    assert body == "Hi Grace, from Maison Aurelle"
    assert m.fill("Hi {first_name}", "", "X") == "Hi there"


def test_email_link_encodes_subject_and_body():
    link = m.email_link("g@x.com", "A note", "Hi Grace, welcome")
    assert link.startswith("mailto:g@x.com?")
    assert "subject=A%20note" in link and "Hi%20Grace" in link
    assert m.email_link("", "s", "b") == ""


def test_whatsapp_link_normalises_number():
    assert m.wa_number("00852 93154050") == "85293154050"     # drops the 00 intl prefix
    assert m.wa_number("+44 7402 886548") == "447402886548"
    link = m.whatsapp_link("00852 93154050", "Hi Grace")
    assert link == "https://wa.me/85293154050?text=Hi%20Grace"
    assert m.whatsapp_link("", "hi") == ""


def test_stage_and_status_suggestions():
    assert m.suggest_for_status("lapsed") == "winback"
    assert m.suggest_for_status("active") == "new_arrival"
    assert m.suggest_for_stage("on its way") == "on_its_way"
    assert m.suggest_for_stage("delivered") == "delivered"
    # every suggestion points at a real template
    keys = {t["key"] for t in m.templates_public()}
    for s in ("winback", "new_arrival", "on_its_way", "delivered", "thank_you"):
        assert s in keys
