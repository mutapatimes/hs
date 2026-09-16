"""Team sign-in for the console and the CMS.

The owner holds the enable keys. Everyone else is on a team list the owner manages at
/console/team and signs in with a link emailed to their work address. A team member gets the
content editor and the blog; the console's business numbers stay with the owner. Removing a
person ends their session at once.
"""
import pytest
from fastapi.testclient import TestClient

from halia import notify
from halia.api import console, shopify_auth, staff_auth
from halia.api.app import app
from halia.store import ShopStore

CLAUDIA = "claudia@haliascore.com"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = ShopStore(db_path=tmp_path / "t.db")
    monkeypatch.setattr(shopify_auth, "_shop_store", store)
    monkeypatch.setattr("halia.config.CONSOLE_KEY", "own3r")
    monkeypatch.setattr("halia.config.ADMIN_KEY", "s3cret")
    monkeypatch.setattr("halia.config.HALIA_APP_URL", "http://testserver")   # http: the test client drops secure cookies
    sent = []
    monkeypatch.setattr(notify, "email_configured", lambda: True)
    monkeypatch.setattr(notify, "send_email", lambda to, subject, html, *a, **k: sent.append((to, subject, html)) or True)
    console._REV_CACHE.clear()
    yield TestClient(app), store, sent


def _owner(c):
    c.post("/console/login", data={"key": "own3r"})


def _link_from(html):
    import re
    m = re.search(r"href=['\"](http://testserver/admin/login/link\?t=[^'\"]+)['\"]", html)
    assert m, "no sign-in link in the email"
    return m.group(1).replace("&amp;", "&").replace("http://testserver", "")


def test_owner_adds_a_team_member_and_the_page_lists_them(env):
    c, store, _ = env
    assert c.post("/console/team/add", data={"email": CLAUDIA, "name": "Claudia"}).status_code == 403
    _owner(c)
    r = c.post("/console/team/add", data={"email": CLAUDIA, "name": "Claudia"}, follow_redirects=True)
    assert r.status_code == 200 and "Claudia can now sign in" in r.text
    assert store.get_editor(CLAUDIA)["name"] == "Claudia"
    page = c.get("/console/team").text
    assert CLAUDIA in page and "Remove" in page


def test_an_unknown_address_gets_the_same_answer_and_no_email(env):
    c, store, sent = env
    r = c.post("/admin/login/email", data={"email": "stranger@example.com"})
    assert r.status_code == 200 and "Check your email" in r.text
    assert sent == []


def test_a_team_member_signs_in_by_link_and_gets_the_cms_not_the_console(env):
    c, store, sent = env
    store.add_editor(CLAUDIA, "Claudia")
    r = c.post("/admin/login/email", data={"email": CLAUDIA})
    assert "Check your email" in r.text and len(sent) == 1 and sent[0][0] == CLAUDIA
    link = _link_from(sent[0][2])
    r = c.get(link, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert staff_auth.SESSION_COOKIE in r.headers.get("set-cookie", "")
    admin = c.get("/admin").text
    assert "Content editor" in admin and "Claudia" in admin           # signed in, named in the shell
    assert c.get("/admin/blog").status_code == 200
    # the console is the owner's: a team member sees the sign-in card, not the numbers
    con = c.get("/console").text
    assert "Console dashboard" in con and "Access key" in con
    assert c.get("/console/data.json").status_code == 403
    # the nav shown to a team member is the CMS only
    assert "/console/revenue" not in admin and "/admin/blog" in admin


def test_removing_a_team_member_ends_their_session(env):
    c, store, sent = env
    store.add_editor(CLAUDIA, "Claudia")
    c.post("/admin/login/email", data={"email": CLAUDIA})
    c.get(_link_from(sent[0][2]))
    assert "Content editor" in c.get("/admin").text
    store.remove_editor(CLAUDIA)
    assert "Access key" in c.get("/admin").text                       # back at the gate


def test_links_expire_and_cannot_be_forged(env):
    c, store, sent = env
    store.add_editor(CLAUDIA, "Claudia")
    stale = staff_auth.link_token(CLAUDIA, ttl=-1)
    assert c.get(f"/admin/login/link?t={stale}").status_code == 401
    forged = staff_auth.link_token(CLAUDIA).rsplit("|", 1)[0] + "|" + "0" * 64
    assert c.get(f"/admin/login/link?t={forged}").status_code == 401
    # a link for someone who is not on the team signs nobody in, even though it is well signed
    assert c.get(f"/admin/login/link?t={staff_auth.link_token('nobody@haliascore.com')}").status_code == 401


def test_the_owners_old_style_session_still_works(env):
    c, store, _ = env
    old = staff_auth.make_session()                                   # two-part cookie, no email
    c.cookies.set(staff_auth.SESSION_COOKIE, old)
    assert c.get("/console/data.json").status_code == 200
    assert "Content editor" in c.get("/admin").text


def test_a_post_saved_by_a_team_member_carries_their_byline(env):
    c, store, sent = env
    store.add_editor(CLAUDIA, "Claudia Rossi")
    c.post("/admin/login/email", data={"email": CLAUDIA})
    c.get(_link_from(sent[0][2]))
    c.post("/admin/blog/save", data={"title": "A first note", "body_html": "<p>Hello</p>", "author": ""})
    assert store.get_post("a-first-note")["author"] == "Claudia Rossi"
