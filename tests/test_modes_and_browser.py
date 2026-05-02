"""Tests for runtime modes, chain resolution, and BrowserProvider readiness."""

from __future__ import annotations

from pathlib import Path

from openclaw.providers.browser import BrowserProvider, BrowserReadiness
from openclaw.providers.outlook import OutlookMonarchSelectorPack
from openclaw.runtime.modes import (
    PROVIDER_CHAINS,
    RuntimeMode,
    make_resolver,
)
from openclaw.types.core import ProfileContext


# --- mode chain resolution --------------------------------------------------


def test_chain_keys_consistent_across_modes():
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


# --- BrowserProvider readiness ---------------------------------------------


def test_browser_supports_false_when_not_enabled():
    p = BrowserProvider(readiness=BrowserReadiness(enabled=False))
    assert not p.supports("outlook.mail.list", ProfileContext())


def test_browser_supports_false_when_no_selector_pack(tmp_path: Path):
    p = BrowserProvider(
        readiness=BrowserReadiness(enabled=True, base_dir=tmp_path, selector_pack=None)
    )
    assert not p.supports("outlook.mail.list", ProfileContext())


def test_browser_supports_true_for_outlook_mail_list_with_monarch_pack(tmp_path: Path):
    p = BrowserProvider(
        readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=OutlookMonarchSelectorPack(),
        )
    )
    assert p.supports("outlook.mail.list", ProfileContext())
    # Pack covers ONLY outlook.mail.list — anything else returns False.
    assert not p.supports("outlook.mail.read", ProfileContext())
    assert not p.supports("teams.chat.list", ProfileContext())


def test_browser_invoke_for_unsupported_tool_returns_unavailable(tmp_path: Path):
    """Tools not implemented by BrowserProvider in milestone (2) get
    provider_unavailable, regardless of readiness state.
    """
    from openclaw.types.core import ToolCall

    p = BrowserProvider(
        readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=OutlookMonarchSelectorPack(),
        )
    )
    try:
        result = p.invoke(ToolCall(tool="teams.chat.list", inputs={}))
        assert not result.ok
        assert result.error_code == "provider_unavailable"
    finally:
        p.close()
