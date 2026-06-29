"""Klaviyo segment builder: correct definitions + idempotent ensure_defaults."""
from halia.adapters.klaviyo_segments import KlaviyoSegments, default_segments


def test_default_segments_cover_grades_and_specials():
    names = {n for n, _ in default_segments()}
    assert "Halia · A* — Hidden VICs" in names
    assert {"Halia · A", "Halia · B", "Halia · C"} <= names
    assert "Halia · Priority (A*/A)" in names and "Halia · Hidden VIC" in names


def test_grade_condition_shape():
    name, definition = default_segments()[0]  # A*
    cond = definition["condition_groups"][0]["conditions"][0]
    # Klaviyo requires custom props referenced as properties['name'].
    assert cond["type"] == "profile-property" and cond["property"] == "properties['Halia Grade']"
    assert cond["filter"] == {"type": "string", "operator": "equals", "value": "A*"}


def test_priority_segment_is_two_or_conditions():
    definition = dict(default_segments())["Halia · Priority (A*/A)"]
    conds = definition["condition_groups"][0]["conditions"]
    assert [c["filter"]["value"] for c in conds] == ["A*", "A"]


class FakeKlaviyo:
    """Records create calls; reports two segments as already existing."""

    def __init__(self):
        self.created = []

    def __call__(self, method, url, body):
        if method == "GET":
            return 200, {"data": [{"attributes": {"name": "Halia · B"}},
                                  {"attributes": {"name": "Halia · C"}}]}
        self.created.append(body["data"]["attributes"]["name"])
        return 201, {"data": {"id": "seg_1"}}


def test_ensure_defaults_skips_existing():
    fake = FakeKlaviyo()
    result = KlaviyoSegments(transport=fake).ensure_defaults()
    assert set(result["skipped"]) == {"Halia · B", "Halia · C"}
    assert "Halia · A* — Hidden VICs" in result["created"]
    assert "Halia · B" not in fake.created  # existing ones not re-created
