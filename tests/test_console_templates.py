"""Console template packs: added at the top of a client's own list, other settings untouched."""
import json

from halia.api.console import import_template_pack


class _Store:
    def __init__(self, raw):
        self.raw = raw
    def get_settings_raw(self, shop):
        return self.raw
    def save_settings(self, shop, data_json):
        self.raw = data_json


def test_pack_goes_on_top_and_replaces_same_names_keeping_other_settings():
    st = _Store(json.dumps({"sender_name": "Val", "vic_threshold": 9000,
                            "email_templates": [{"name": "Old", "body": "x", "category": "General"},
                                                {"name": "Invite", "body": "old invite", "category": "General"}]}))
    pack = [{"name": "Invite", "category": "Launch", "body": "Hey {first_name}, come on Friday"},
            {"name": "Thanks", "category": "Launch replies", "body": "Thank you!"},
            {"name": "", "body": "no name is dropped"}]
    out = import_template_pack("shopx", pack, store=st)
    data = json.loads(st.raw)
    assert out == {"added": 2, "total": 3}
    assert [t["name"] for t in data["email_templates"]] == ["Invite", "Thanks", "Old"]
    assert data["email_templates"][0]["body"] == "Hey {first_name}, come on Friday"
    assert data["sender_name"] == "Val" and data["vic_threshold"] == 9000


def test_a_store_on_house_defaults_keeps_them_below_the_pack(monkeypatch):
    monkeypatch.setattr("halia.api.settings.settings_for",
                        lambda shop: {"email_templates": [{"name": "Default", "body": "d", "category": "Welcome"}]})
    st = _Store(None)
    import_template_pack("shopx", {"templates": [{"name": "Invite", "body": "b", "category": "Launch"}]}, store=st)
    assert [t["name"] for t in json.loads(st.raw)["email_templates"]] == ["Invite", "Default"]
