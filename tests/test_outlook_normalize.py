"""Outlook normalize + taint tests."""

from __future__ import annotations

from openclaw.providers.outlook.types import (
    OutlookMessageSummary,
    to_taint_tags,
)


def _summary(**kwargs):
    defaults = dict(
        id="msg_x",
        from_name="Alice",
        from_address="alice@example.com",
        subject="hello",
        received_at="2026-05-02T00:00:00+00:00",
        snippet="hi",
        is_read=False,
    )
    defaults.update(kwargs)
    return OutlookMessageSummary(**defaults)


def test_message_summary_to_dict_roundtrip():
    s = _summary()
    d = s.to_dict()
    assert d["id"] == "msg_x"
    assert d["from_address"] == "alice@example.com"
    assert d["received_at"].startswith("2026-")


def test_message_summary_fields_are_tainted():
    """Required: every external field carries taint per spec §11.2."""
    msgs = [_summary()]
    tags = to_taint_tags(msgs)
    fields = {t.field for t in tags}
    for expected in (
        "messages[0].from_name",
        "messages[0].from_address",
        "messages[0].subject",
        "messages[0].received_at",
        "messages[0].snippet",
    ):
        assert expected in fields, f"missing taint tag for {expected}"


def test_to_taint_tags_skips_none_fields():
    """Optional fields that came back as None do not get taint tags."""
    msgs = [_summary(from_name=None, snippet=None, received_at=None)]
    fields = {t.field for t in to_taint_tags(msgs)}
    assert "messages[0].subject" in fields
    assert "messages[0].from_address" in fields
    assert "messages[0].from_name" not in fields
    assert "messages[0].snippet" not in fields
    assert "messages[0].received_at" not in fields


def test_to_taint_tags_all_marked_untrusted():
    msgs = [_summary()]
    for tag in to_taint_tags(msgs):
        assert tag.trust.value == "untrusted_user_content"


def test_to_taint_tags_indexes_multiple_messages():
    msgs = [_summary(id="msg_a"), _summary(id="msg_b"), _summary(id="msg_c")]
    fields = {t.field for t in to_taint_tags(msgs)}
    for i in range(3):
        assert f"messages[{i}].subject" in fields
