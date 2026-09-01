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
    to_async = js.index("item.to && item.to.getAsync")
    sender = js.index("item.organizer || item.from || item.sender")
    plain_to = js.index("item.to && item.to.length")
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
