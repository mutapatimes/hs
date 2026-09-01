"""The Outlook add-in: the manifest a mailbox installs, and the pane it frames.

Two things here are worth more than the rest. The manifest is what Outlook validates before it
will install anything, so a malformed one fails silently in someone else's mailbox. And the task
pane is loaded in an iframe, which the site-wide security headers block by default — that failure
looks like a blank panel with nothing in any log, so it is pinned down here instead.
"""
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from halia import config
from halia.api.app import app
from halia.api.outlook_addon import manifest_xml

_NS = "{http://schemas.microsoft.com/office/appforoffice/1.1}"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config, "HALIA_APP_URL", "https://haliascore.com")
    return TestClient(app)


def test_the_manifest_is_valid_enough_to_install(client):
    x = ET.fromstring(client.get("/addons/outlook/manifest.xml").text)
    kids = [c.tag.replace(_NS, "") for c in x if isinstance(c.tag, str)]
    # A mail manifest is a fixed sequence; out of order, Outlook rejects the whole file.
    assert kids[:6] == ["Id", "Version", "ProviderName", "DefaultLocale", "DisplayName",
                        "Description"]
    assert "Rule" in kids, "a mail manifest without activation rules will not install"
    assert x.findtext(_NS + "Permissions") == "ReadWriteItem"   # setSelectedDataAsync needs it
    assert x.findtext(_NS + "Id") == config.OUTLOOK_ADDIN_ID


def test_every_url_in_the_manifest_is_https_and_ours(client):
    text = client.get("/addons/outlook/manifest.xml").text
    x = ET.fromstring(text)
    urls = [e.get("DefaultValue") for e in x.iter() if (e.get("DefaultValue") or "").startswith("http")]
    assert urls, "the manifest should point at something"
    for u in urls:
        assert u.startswith("https://haliascore.com/"), u
    assert "http://haliascore" not in text                       # never plain http


def test_the_manifest_promises_no_surface_outlook_cannot_give(client):
    # Outlook on iOS and Android run read-mode add-ins only. Declaring a mobile form factor would
    # put a button in front of associates that opens nothing.
    text = client.get("/addons/outlook/manifest.xml").text
    assert "MobileFormFactor" not in text
    assert "MobileMessageReadCommandSurface" not in text


def test_the_id_is_stable(client):
    # Outlook keys an installed add-in on this GUID. A new one reads as a different add-in and
    # installs a second copy beside the first.
    assert client.get("/addons/outlook/manifest.xml").text == manifest_xml()
    assert manifest_xml() == manifest_xml()


def test_outlook_is_allowed_to_frame_the_pane(client):
    # The site-wide middleware sets frame-ancestors 'none' + X-Frame-Options: DENY on anything
    # that does not set its own CSP. Inside Outlook that is a blank panel and no error anywhere.
    for path in ("/addons/outlook/taskpane", "/addons/outlook/commands"):
        r = client.get(path)
        assert r.status_code == 200
        csp = r.headers["content-security-policy"]
        assert "https://outlook.office.com" in csp and "'none'" not in csp
        assert "x-frame-options" not in {k.lower() for k in r.headers}, path


def test_everything_else_keeps_the_strict_headers(client):
    # Only the two framed pages are exempt; the manifest and the assets stay locked down.
    for path in ("/addons/outlook/manifest.xml", "/addons/outlook/asset/icon-64.png"):
        r = client.get(path)
        assert r.headers["content-security-policy"] == "frame-ancestors 'none'", path
        assert r.headers["x-frame-options"] == "DENY", path


def test_the_pane_and_its_script_serve_and_carry_no_secret(client):
    page = client.get("/addons/outlook/taskpane")
    assert page.status_code == 200 and "__BASE__" not in page.text     # base substituted
    assert "office.js" in page.text and "/static/halia-shape.js" in page.text
    js = client.get("/addons/outlook/taskpane.js")
    assert js.status_code == 200 and "X-Halia-Ext-Token" in js.text
    # These are public pages: a token must arrive from the associate, never be baked in.
    for text in (page.text, js.text):
        assert "shpat_" not in text and "HALIA_" not in text


def test_the_manifest_and_pane_need_no_sign_in(client):
    # Sideloading and admin deployment both fetch these unauthenticated. If either starts
    # requiring a session, installing the add-in stops working with no useful error.
    for path in ("/addons/outlook/manifest.xml", "/addons/outlook/taskpane",
                 "/addons/outlook/taskpane.js", "/addons/outlook/asset/icon-16.png"):
        assert client.get(path).status_code == 200, path


def test_an_unknown_asset_is_not_a_path_traversal(client):
    assert client.get("/addons/outlook/asset/nope.png").status_code == 404
    assert client.get("/addons/outlook/asset/..%2F..%2Fconfig.py").status_code in (404, 400)


def test_halia_is_offered_on_meetings_as_well_as_messages(client):
    # A visit is as often agreed in the calendar as in an email, so the add-in appears on the
    # organiser's and the attendee's meeting windows too.
    x = ET.fromstring(client.get("/addons/outlook/manifest.xml").text)
    xsi = "{http://www.w3.org/2001/XMLSchema-instance}type"
    points = [e.get(xsi) for e in x.iter() if e.tag.endswith("ExtensionPoint")]
    assert "AppointmentOrganizerCommandSurface" in points
    assert "AppointmentAttendeeCommandSurface" in points
    rules = {(e.get("ItemType"), e.get("FormType")) for e in x.iter()
             if e.tag.endswith("Rule") and e.get("ItemType")}
    # Without the Appointment rules the ribbon buttons never activate.
    assert ("Appointment", "Edit") in rules and ("Appointment", "Read") in rules
    assert ("Message", "Edit") in rules and ("Message", "Read") in rules


def test_the_pane_sends_a_real_invitation_rather_than_a_link(client):
    js = client.get("/addons/outlook/taskpane.js").text
    # The whole point of being inside a calendar client.
    assert "displayNewAppointmentForm" in js
    assert "requiredAttendees" in js and "links.title" in js
    # And it still degrades to the sentence when the host cannot open a form.
    assert "bookSend" in js


def test_the_pane_reads_the_sender_when_reading_a_message(client):
    js = client.get("/addons/outlook/taskpane.js").text
    # In compose `to` is a Recipients object and the client is who it is going to. Reading a
    # message, `to` is a plain array holding US, so the client is the sender. Getting this the
    # wrong way round looked up the associate as if they were their own client.
    to_async = js.index("it.to && it.to.getAsync")
    sender = js.index("it.organizer || it.from || it.sender")
    plain_to = js.index("it.to && it.to.length")
    assert to_async < sender < plain_to, "the sender must be preferred over a read-mode `to`"


def test_a_tick_is_not_a_text_field(client):
    # `input { width:100% }` stretched the checkbox across the row and pushed the product's name
    # out of sight, which read as an empty list.
    page = client.get("/addons/outlook/taskpane").text
    assert "input[type=checkbox] { width:auto" in page


def test_the_pane_offers_a_basket_as_well_as_a_selection(client):
    js = client.get("/addons/outlook/taskpane.js").text
    assert "/v1/extension/cart_link" in js and "/v1/extension/catalogue" in js


def test_the_pane_shows_the_grade_and_keeps_sign_out_out_of_the_way(client):
    page = client.get("/addons/outlook/taskpane").text
    js = client.get("/addons/outlook/taskpane.js").text
    assert 'id="grade"' in page and 'd.grade' in js
    assert 'class="quiet" id="signout"' in page      # a footnote, not a button beside their name


def test_nothing_in_the_pane_tells_an_associate_to_ask_a_manager(client):
    page = client.get("/addons/outlook/taskpane").text
    assert "manager" not in page.lower()


_V0 = "{http://schemas.microsoft.com/office/mailappversionoverrides}"
_V1 = "{http://schemas.microsoft.com/office/mailappversionoverrides/1.1}"
_XSI = "{http://www.w3.org/2001/XMLSchema-instance}type"


def test_the_two_schema_generations_nest_as_the_spec_demands(client):
    # The 1.1 element must be the LAST child of the 1.0 element and inherits nothing from it, so
    # it restates its own Requirements, Hosts and Resources. Older clients read only the outer
    # block and see exactly what they saw before.
    x = ET.fromstring(client.get("/addons/outlook/manifest.xml").text)
    v0 = x.find(_V0 + "VersionOverrides")
    kids = [c.tag for c in v0]
    assert kids[-1] == _V1 + "VersionOverrides", "V1_1 must be the last child of V1_0"
    v1 = v0.find(_V1 + "VersionOverrides")
    inner = {c.tag.replace(_V1, "") for c in v1}
    assert {"Requirements", "Hosts", "Resources"} <= inner
    # and both generations carry the same four ribbon surfaces, from the same template
    def points(root, ns):
        return [e.get(_XSI) for e in root.iter() if e.tag == ns + "ExtensionPoint"]
    four = ["MessageComposeCommandSurface", "MessageReadCommandSurface",
            "AppointmentOrganizerCommandSurface", "AppointmentAttendeeCommandSurface"]
    assert [p for p in points(v0, _V0) if p != "LaunchEvent"] == four
    assert [p for p in points(v1, _V1) if p != "LaunchEvent"] == four


def test_the_read_pane_is_pinnable_and_only_where_pinning_exists(client):
    x = ET.fromstring(client.get("/addons/outlook/manifest.xml").text)
    v0 = x.find(_V0 + "VersionOverrides")
    v1 = v0.find(_V1 + "VersionOverrides")
    # Pinning is a 1.1-only element; putting it in the 1.0 block would invalidate that manifest
    # for every older client.
    assert not [e for e in v0.iter() if e.tag == _V0 + "SupportsPinning"]
    pins = [e for e in v1.iter() if e.tag == _V1 + "SupportsPinning"]
    assert len(pins) == 2 and all(e.text == "true" for e in pins)   # the two read surfaces


def test_sending_fires_the_auto_log_and_can_never_hold_up_mail(client):
    x = ET.fromstring(client.get("/addons/outlook/manifest.xml").text)
    v1 = x.find(_V0 + "VersionOverrides").find(_V1 + "VersionOverrides")
    ev = [e for e in v1.iter() if e.tag == _V1 + "LaunchEvent"]
    assert len(ev) == 1
    assert ev[0].get("Type") == "OnMessageSend"
    # PromptUser is the guarantee: if Halia is broken or unreachable, Outlook sends the mail.
    assert ev[0].get("SendMode") == "PromptUser"
    # and the classic-Windows runtime override points at the standalone handler
    overrides = [e.get("resid") for e in v1.iter() if e.tag == _V1 + "Override"]
    assert overrides == ["eventsJs"]
    js = client.get("/addons/outlook/events.js").text
    assert "allowEvent: true" in js and "haliaOnSend" in js
    assert "__BASE__" not in js                       # the base is baked in at serve time
    assert js.index("finish();") < js.index("fetch(")  # the timeout path completes the event


def test_reading_a_message_is_a_first_class_desk(client):
    js = client.get("/addons/outlook/taskpane.js").text
    # Every action used to fail in read mode with "Open a reply first." Now it opens a reply
    # already written.
    assert "displayReplyForm" in js and "Open a reply first" not in js
    assert "/v1/extension/brief" in js and "/v1/extension/remember" in js
    assert "/v1/extension/history" in js and "/v1/extension/appointments" in js
    assert "/v1/capture" in js                        # an unknown sender is one tap from the book
    assert "ItemChanged" in js and "RecipientsChanged" in js
    assert "roamingSettings" in js                    # what the on-send handler signs in with
    # The standing shows reasons, the play and orders, and never the latent value (the field is
    # in the lookup response; the pane must not read it).
    assert "d.latent" not in js and "client.latent" not in js


def test_compose_still_gets_its_own_tools(client):
    js = client.get("/addons/outlook/taskpane.js").text
    assert "/v1/extension/polish" in js and "getSelectedDataAsync" in js
    assert "fillSubject" in js                        # a template's subject fills an empty draft
