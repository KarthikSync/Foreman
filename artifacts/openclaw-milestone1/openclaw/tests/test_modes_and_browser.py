"""Tests for runtime modes, chain resolution, and BrowserProvider readiness."""

from __future__ import annotations

from pathlib import Path

from openclaw.providers.browser import BrowserProvider, BrowserReadiness, SelectorPack
from openclaw.runtime.modes import (
    PROVIDER_CHAINS,
    RuntimeMode,
    make_resolver,
)
from openclaw.types.core import ProfileContext


# --- mode chain resolution --------------------------------------------------


def test_chain_keys_consistent_across_modes():
    """All modes declare chains for the same set of tools."""
    keys = [set(PROVIDER_CHAINS[m].keys()) for m in RuntimeMode]
    assert all(k == keys[0] for k in keys[1:]), keys


def test_serve_local_does_not_route_to_fake():
    chain = make_resolver(RuntimeMode.SERVE_LOCAL)("outlook.mail.list")
    assert "fake_outlook" not in chain
    assert chain == ("browser",)


def test_harness_fake_routes_outlook_to_fake():
    chain = make_resolver(RuntimeMode.HARNESS_FAKE)("outlook.mail.list")
    assert chain == ("fake_outlook",)


def test_harness_live_routes_outlook_to_browser():
    chain = make_resolver(RuntimeMode.HARNESS_LIVE)("outlook.mail.list")
    assert chain == ("browser",)


def test_resolver_returns_empty_for_unknown_tool():
    assert make_resolver(RuntimeMode.SERVE_LOCAL)("not.a.real.tool") == ()


# --- BrowserProvider declarative readiness ---------------------------------


def test_browser_supports_false_when_not_enabled():
    p = BrowserProvider(readiness=BrowserReadiness(enabled=False))
    assert not p.supports("outlook.mail.list", ProfileContext())


def test_browser_supports_false_when_no_selector_pack(tmp_path: Path):
    p = BrowserProvider(
        readiness=BrowserReadiness(enabled=True, base_dir=tmp_path, selector_pack=None)
    )
    assert not p.supports("outlook.mail.list", ProfileContext())


def test_browser_supports_true_when_pack_includes_tool(tmp_path: Path):
    p = BrowserProvider(
        readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=SelectorPack(
                name="hypothetical_pack",
                supported_tools=frozenset({"outlook.mail.list"}),
            ),
        )
    )
    assert p.supports("outlook.mail.list", ProfileContext())
    assert not p.supports("teams.chat.list", ProfileContext())


def test_browser_invoke_returns_unavailable_in_milestone_1(tmp_path: Path):
    """Even with full readiness, invoke() returns provider_unavailable
    in milestone (1). Selectors arrive in the next milestone.
    """
    from openclaw.types.core import ToolCall

    p = BrowserProvider(
        readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=SelectorPack(
                name="hypothetical_pack",
                supported_tools=frozenset({"outlook.mail.list"}),
            ),
        )
    )
    try:
        result = p.invoke(ToolCall(tool="outlook.mail.list", inputs={}))
        assert not result.ok
        assert result.error_code == "provider_unavailable"
    finally:
        p.close()
