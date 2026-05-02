"""Tool Registry tests."""

from __future__ import annotations

from openclaw.registry.registry import default_registry


def test_default_registry_contains_expected_tools():
    reg = default_registry()
    names = {s.name for s in reg.list_all()}
    assert {
        "outlook.mail.list",
        "outlook.mail.read",
        "memory.preferences.get",
        "memory.preferences.set",
        "browser.click",
    }.issubset(names)


def test_list_visible_excludes_primitives_by_default():
    reg = default_registry()
    visible = {s.name for s in reg.list_visible(primitives_enabled=False)}
    assert "browser.click" not in visible
    assert "outlook.mail.list" in visible


def test_list_visible_includes_primitives_when_enabled():
    reg = default_registry()
    visible = {s.name for s in reg.list_visible(primitives_enabled=True)}
    assert "browser.click" in visible


def test_register_duplicate_raises():
    import pytest

    reg = default_registry()
    spec = reg.get("outlook.mail.list")
    assert spec is not None
    with pytest.raises(ValueError):
        reg.register(spec)
