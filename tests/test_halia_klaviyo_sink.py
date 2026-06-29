"""KlaviyoSink builds the correct upsert body (against a fake transport)."""
import pytest

from halia.adapters.klaviyo_sink import KlaviyoError, KlaviyoSink
from halia.schema import ScoreResult


def _result(email, grade="A*", score=99):
    return ScoreResult(
        matched=True, flagged=True, tier="A1", grade=grade, score=score, is_priority=True,
        signal_count=2, signals=["Work email"], reasons="Work email: GS", gesture="",
        spend=400.0, hidden_vic=True, customer_id="c1", email=email, phone=None,
    )


class FakeKlaviyo:
    def __init__(self, status=200):
        self.status = status
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        return self.status, {"data": {"id": "01ABC", "type": "profile"}}


def test_push_builds_upsert_body_with_properties():
    fake = FakeKlaviyo()
    KlaviyoSink(transport=fake).push_many([_result("vic@x.com")])
    assert len(fake.bodies) == 1
    attrs = fake.bodies[0]["data"]["attributes"]
    assert fake.bodies[0]["data"]["type"] == "profile"
    assert attrs["email"] == "vic@x.com"
    props = attrs["properties"]
    # Clean, Title-Case property names so the Klaviyo panel reads well.
    assert props["Halia Grade"] == "A*" and props["Halia Score"] == 99
    assert props["Halia Hidden VIC"] is True
    assert "Halia Reasons" in props and "Halia Last Scored" in props
    # Fired signals as a list property (segmentable) + the count.
    assert props["Halia Signals"] == ["Work email"] and props["Halia Signal Count"] == 2


def test_profiles_without_email_are_skipped():
    fake = FakeKlaviyo()
    KlaviyoSink(transport=fake).push_many([_result(None), _result("ok@x.com")])
    assert [b["data"]["attributes"]["email"] for b in fake.bodies] == ["ok@x.com"]


def test_non_2xx_raises():
    with pytest.raises(KlaviyoError):
        KlaviyoSink(transport=FakeKlaviyo(status=403)).push_one(_result("x@x.com"))


def test_missing_key_and_transport_raises():
    # With no key AND no injected transport, sending must fail loudly (not silently
    # fall back to a real key from the environment).
    sink = KlaviyoSink()
    sink.api_key = None
    sink._transport = None
    with pytest.raises(KlaviyoError):
        sink.push_one(_result("x@x.com"))
