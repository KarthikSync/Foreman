"""Engine-level integration tests covering the v0.1 acceptance criteria."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from openclaw.runtime.bootstrap import build_engine
from openclaw.runtime.modes import RuntimeMode
from openclaw.types.core import ToolCall


def test_outlook_mail_list_returns_tainted_messages_in_harness_fake():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        result = engine.execute(
            ToolCall(
                tool="outlook.mail.list",
                inputs={"limit": 5, "unread_only": True},
            )
        )

        assert result.ok, result.error_message
        msgs = result.data["messages"]
        assert len(msgs) >= 1
        assert all(not m["is_read"] for m in msgs)
        tainted_fields = {t.field for t in result.taint}
        for i in range(len(msgs)):
            assert f"messages[{i}].subject" in tainted_fields
            assert f"messages[{i}].snippet" in tainted_fields
            assert f"messages[{i}].from" in tainted_fields


def test_fake_provider_NOT_in_production_chain():
    """The blocker fix. SERVE_LOCAL must NOT route Outlook to fake_outlook —
    it must route to browser, which (in v0.1) is not yet ready, so the call
    returns provider_unavailable. This is the correct production behavior:
    refusal until the live provider lands.
    """
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.SERVE_LOCAL)
        result = engine.execute(
            ToolCall(tool="outlook.mail.list", inputs={"limit": 1})
        )
        assert not result.ok
        assert result.error_code == "provider_unavailable"

        # Audit log: no envelope should attribute SERVE_LOCAL outlook calls to
        # the fake provider.
        envelopes = json.loads(
            "[" + ",".join((Path(d) / "audit.log").read_text().splitlines()) + "]"
        )
        outlook_envs = [e for e in envelopes if e["tool"] == "outlook.mail.list"]
        assert outlook_envs
        for e in outlook_envs:
            assert e["provider"] != "fake_outlook"


def test_outlook_mail_read_carries_body_taint_in_harness_fake():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        result = engine.execute(
            ToolCall(tool="outlook.mail.read", inputs={"id": "msg_001"})
        )
        assert result.ok
        fields = {t.field for t in result.taint}
        assert "body" in fields
        assert "subject" in fields


def test_primitive_hidden_by_default_and_refused_when_invoked():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        visible = {
            s.name for s in engine.registry.list_visible(primitives_enabled=False)
        }
        assert "browser.click" not in visible

        result = engine.execute(ToolCall(tool="browser.click", inputs={"ref": "x"}))
        assert not result.ok
        assert result.error_code == "provider_unavailable"


def test_primitive_visible_when_enabled():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(
            base_dir=Path(d),
            mode=RuntimeMode.HARNESS_FAKE,
            primitives_enabled=True,
        )
        visible = {
            s.name for s in engine.registry.list_visible(primitives_enabled=True)
        }
        assert "browser.click" in visible


def test_invalid_input_is_rejected_with_proper_error():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        result = engine.execute(
            ToolCall(
                tool="memory.preferences.set",
                inputs={"key": "totally_invalid", "value": "x"},
            )
        )
        assert not result.ok
        assert result.error_code == "invalid_input"


def test_unknown_tool_returns_tool_not_found():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        result = engine.execute(ToolCall(tool="does.not.exist", inputs={}))
        assert not result.ok
        assert result.error_code == "tool_not_found"


def test_audit_log_envelope_has_required_fields():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        engine.execute(ToolCall(tool="outlook.mail.list", inputs={"limit": 1}))

        audit_log = Path(d) / "audit.log"
        lines = audit_log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        env = json.loads(lines[0])

        for key in (
            "tool_call_id",
            "session_id",
            "profile_id",
            "tool",
            "tool_version",
            "provider",
            "provider_attempt",
            "action_class",
            "inputs_redacted",
            "taint_inputs",
            "taint_outputs",
            "requires_approval",
            "started_at",
            "duration_ms",
            "outcome",
            "correlation_id",
        ):
            assert key in env, f"missing field: {key}"

        assert env["tool"] == "outlook.mail.list"
        assert env["outcome"] == "success"
        assert env["profile_id"] == "default"
        assert env["provider"] == "fake_outlook"
        assert env["action_class"] == "read"
        assert len(env["taint_outputs"]) > 0


def test_memory_preferences_roundtrip_serve_local():
    """Memory works in both modes — same provider chain for both."""
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.SERVE_LOCAL)
        set_result = engine.execute(
            ToolCall(
                tool="memory.preferences.set",
                inputs={"key": "default_signature", "value": "Best, Sam"},
            )
        )
        assert set_result.ok

        get_result = engine.execute(
            ToolCall(
                tool="memory.preferences.get",
                inputs={"key": "default_signature"},
            )
        )
        assert get_result.ok
        assert get_result.data["value"] == "Best, Sam"


def test_session_id_is_carried_through_envelope():
    """ToolCall lets the caller pass an explicit session_id; the envelope
    carries it unchanged.
    """
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        explicit = "sess_TEST_FIXTURE_123456789012"
        engine.execute(
            ToolCall(
                tool="outlook.mail.list",
                inputs={"limit": 1},
                session_id=explicit,
            )
        )
        env = json.loads((Path(d) / "audit.log").read_text().strip().splitlines()[0])
        assert env["session_id"] == explicit
