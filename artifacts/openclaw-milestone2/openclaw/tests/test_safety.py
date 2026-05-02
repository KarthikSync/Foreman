"""Safety Governor unit tests."""

from __future__ import annotations

from openclaw.registry.registry import default_registry
from openclaw.safety.governor import SafetyGovernor
from openclaw.types.errors import ErrorCode


def test_classify_known_tool():
    g = SafetyGovernor(default_registry())
    cls = g.classify("outlook.mail.list")
    assert cls is not None
    assert cls.value == "read"


def test_classify_unknown_tool_returns_none():
    g = SafetyGovernor(default_registry())
    assert g.classify("not.a.tool") is None


def test_evaluate_unknown_tool():
    g = SafetyGovernor(default_registry())
    decision = g.evaluate("not.a.tool", {})
    assert not decision.allow
    assert decision.error_code == ErrorCode.TOOL_NOT_FOUND


def test_evaluate_invalid_input():
    g = SafetyGovernor(default_registry())
    # outlook.mail.list does not allow `foo`
    decision = g.evaluate("outlook.mail.list", {"foo": "bar"})
    assert not decision.allow
    assert decision.error_code == ErrorCode.INVALID_INPUT


def test_evaluate_primitive_gated_off():
    g = SafetyGovernor(default_registry(), primitives_enabled=False)
    decision = g.evaluate("browser.click", {"ref": "x"})
    assert not decision.allow
    assert decision.error_code == ErrorCode.PROVIDER_UNAVAILABLE


def test_evaluate_primitive_allowed_when_enabled_passes_governor():
    """Governor allows the primitive; the provider chain is what would
    actually fulfill or reject it. We only test the governor decision here.
    """
    g = SafetyGovernor(default_registry(), primitives_enabled=True)
    decision = g.evaluate("browser.click", {"ref": "x"})
    assert decision.allow


def test_evaluate_read_passes():
    g = SafetyGovernor(default_registry())
    decision = g.evaluate("outlook.mail.list", {"limit": 5, "unread_only": True})
    assert decision.allow
    assert not decision.requires_approval
