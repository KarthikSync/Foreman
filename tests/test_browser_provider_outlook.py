"""BrowserProvider integration tests for milestone (2).

Covers the reviewer's required tests:
  - live_provider_envelope_shape_matches_fake_provider
  - serve_local_uses_browser_only
  - harness_fake_still_never_launches_browser
  - stdout_stays_clean_during_browser_provider_import
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Callable

from openclaw.audit.trace import AuditTrace
from openclaw.memory.store import MemoryStore
from openclaw.providers.browser import BrowserProvider, BrowserReadiness
from openclaw.providers.fake_outlook import FakeOutlookProvider
from openclaw.providers.memory import MemoryProvider
from openclaw.providers.outlook import OutlookMonarchSelectorPack
from openclaw.registry.registry import default_registry
from openclaw.router.router import ProviderRouter
from openclaw.runtime.engine import OpenClawEngine
from openclaw.runtime.modes import RuntimeMode, make_resolver
from openclaw.safety.governor import SafetyGovernor
from openclaw.types.core import ToolCall

from tests._helpers.outlook import FakeOutlookPage, make_canned_rows


def _build_live_engine_with_injected_page(
    base_dir: Path,
    page_factory: Callable[[], "FakeOutlookPage"],
) -> tuple[OpenClawEngine, BrowserProvider]:
    """Build an engine in HARNESS_LIVE mode with a fake page injected.

    Bypasses build_engine() because the page-factory injection seam is a
    test-only constructor parameter on BrowserProvider.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    registry = default_registry()
    governor = SafetyGovernor(registry, primitives_enabled=False)
    audit = AuditTrace(base_dir / "audit.log")
    memory = MemoryStore(base_dir / "openclaw.db")

    readiness = BrowserReadiness(
        enabled=True,
        base_dir=base_dir,
        selector_pack=OutlookMonarchSelectorPack(),
    )
    browser = BrowserProvider(
        readiness=readiness,
        _page_factory_for_test=page_factory,
    )
    providers = {
        "fake_outlook": FakeOutlookProvider(),
        "memory": MemoryProvider(memory),
        "browser": browser,
    }
    router = ProviderRouter(providers)
    engine = OpenClawEngine(
        registry=registry,
        governor=governor,
        router=router,
        audit=audit,
        chain_resolver=make_resolver(RuntimeMode.HARNESS_LIVE),
    )
    return engine, browser


# --- happy path ------------------------------------------------------------


def test_browser_provider_lists_messages_via_injected_fake_page(tmp_path: Path):
    page_factory = lambda: FakeOutlookPage(rows=make_canned_rows())
    engine, browser = _build_live_engine_with_injected_page(tmp_path, page_factory)
    try:
        result = engine.execute(
            ToolCall(tool="outlook.mail.list", inputs={"limit": 5})
        )
        assert result.ok, result.error_message
        msgs = result.data["messages"]
        assert len(msgs) == 3
        # Required: every external field carries taint.
        fields = {t.field for t in result.taint}
        for i in range(3):
            assert f"messages[{i}].subject" in fields
            assert f"messages[{i}].from_name" in fields
        # Lock should NOT have been acquired (page factory bypasses lifecycle).
        assert browser._lock is not None
        assert not browser._lock.held
    finally:
        engine.close()


# --- error envelopes -------------------------------------------------------


def test_browser_provider_login_redirect_returns_envelope_with_needs_interactive_login(
    tmp_path: Path,
):
    page_factory = lambda: FakeOutlookPage(is_login=True)
    engine, _ = _build_live_engine_with_injected_page(tmp_path, page_factory)
    try:
        result = engine.execute(ToolCall(tool="outlook.mail.list", inputs={}))
        assert not result.ok
        assert result.error_code == "needs_interactive_login"

        env = json.loads(
            (tmp_path / "audit.log").read_text().splitlines()[0]
        )
        assert env["error_code"] == "needs_interactive_login"
        assert env["provider"] == "browser"
    finally:
        engine.close()


def test_browser_provider_unknown_variant_returns_ui_variant_unsupported_envelope(
    tmp_path: Path,
):
    from openclaw.providers.outlook import OutlookVariant

    page_factory = lambda: FakeOutlookPage(variant=OutlookVariant.UNKNOWN)
    engine, _ = _build_live_engine_with_injected_page(tmp_path, page_factory)
    try:
        result = engine.execute(ToolCall(tool="outlook.mail.list", inputs={}))
        assert not result.ok
        assert result.error_code == "ui_variant_unsupported"
    finally:
        engine.close()


# --- envelope-shape parity -------------------------------------------------


def test_live_provider_envelope_shape_matches_fake_provider(tmp_path: Path):
    """Required: a HARNESS_LIVE call (with fake page) and a HARNESS_FAKE call
    must produce envelopes of identical shape and identical message-data
    keys, modulo IDs/timestamps and provider attribution.
    """
    from openclaw.runtime.bootstrap import build_engine

    # Run through HARNESS_FAKE.
    fake_dir = tmp_path / "fake"
    fake_engine = build_engine(base_dir=fake_dir, mode=RuntimeMode.HARNESS_FAKE)
    try:
        fake_engine.execute(
            ToolCall(
                tool="outlook.mail.list",
                inputs={"limit": 3, "unread_only": False},
                session_id="sess_FAKETEST_000000000000",
            )
        )
    finally:
        fake_engine.close()
    fake_env = json.loads((fake_dir / "audit.log").read_text().splitlines()[0])

    # Run through HARNESS_LIVE with injected page.
    live_dir = tmp_path / "live"
    page_factory = lambda: FakeOutlookPage(rows=make_canned_rows())
    live_engine, _ = _build_live_engine_with_injected_page(live_dir, page_factory)
    try:
        live_engine.execute(
            ToolCall(
                tool="outlook.mail.list",
                inputs={"limit": 3, "unread_only": False},
                session_id="sess_LIVETEST_000000000000",
            )
        )
    finally:
        live_engine.close()
    live_env = json.loads((live_dir / "audit.log").read_text().splitlines()[0])

    # Same set of envelope keys.
    assert set(fake_env.keys()) == set(live_env.keys())

    # Same action_class and outcome.
    assert fake_env["action_class"] == live_env["action_class"] == "read"
    assert fake_env["outcome"] == live_env["outcome"] == "success"

    # Same set of taint-output field names (modulo trailing values).
    fake_taint_fields = {t["field"] for t in fake_env["taint_outputs"]}
    live_taint_fields = {t["field"] for t in live_env["taint_outputs"]}
    # Live results may have fewer fields when the page didn't supply them
    # (e.g., received_at). Live's set must be a subset of fake's.
    assert live_taint_fields.issubset(fake_taint_fields), (
        f"unexpected taint fields in live: {live_taint_fields - fake_taint_fields}"
    )

    # Provider attribution is the only expected difference.
    assert fake_env["provider"] == "fake_outlook"
    assert live_env["provider"] == "browser"


def test_live_message_dict_has_same_keys_as_fake(tmp_path: Path):
    from openclaw.runtime.bootstrap import build_engine

    fake_engine = build_engine(base_dir=tmp_path / "f", mode=RuntimeMode.HARNESS_FAKE)
    try:
        fake_result = fake_engine.execute(
            ToolCall(tool="outlook.mail.list", inputs={"limit": 1})
        )
    finally:
        fake_engine.close()

    page_factory = lambda: FakeOutlookPage(rows=make_canned_rows())
    live_engine, _ = _build_live_engine_with_injected_page(tmp_path / "l", page_factory)
    try:
        live_result = live_engine.execute(
            ToolCall(tool="outlook.mail.list", inputs={"limit": 1})
        )
    finally:
        live_engine.close()

    fake_keys = set(fake_result.data["messages"][0].keys())
    live_keys = set(live_result.data["messages"][0].keys())
    assert fake_keys == live_keys, (
        f"shape drift: fake_only={fake_keys-live_keys} live_only={live_keys-fake_keys}"
    )


# --- mode discipline -------------------------------------------------------


def test_serve_local_uses_browser_only(tmp_path: Path):
    """Required: SERVE_LOCAL routes outlook.mail.list to browser, never fake."""
    from openclaw.runtime.bootstrap import build_engine

    engine = build_engine(
        base_dir=tmp_path,
        mode=RuntimeMode.SERVE_LOCAL,
        browser_readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=None,  # no pack → still refuses, never falls to fake
        ),
    )
    try:
        result = engine.execute(
            ToolCall(tool="outlook.mail.list", inputs={"limit": 1})
        )
        assert not result.ok
        assert result.error_code == "provider_unavailable"

        env = json.loads((tmp_path / "audit.log").read_text().splitlines()[0])
        # Provider attribution must NOT be fake_outlook in SERVE_LOCAL.
        assert env["provider"] != "fake_outlook"
    finally:
        engine.close()


def test_harness_fake_still_never_launches_browser(tmp_path: Path):
    """Required: HARNESS_FAKE mode never reaches BrowserProvider.

    We set browser readiness to enabled with a selector pack (the most
    "browser-ready" config) and confirm that an outlook.mail.list call goes
    to fake_outlook, not browser. No profile dir is created.
    """
    from openclaw.runtime.bootstrap import build_engine

    engine = build_engine(
        base_dir=tmp_path,
        mode=RuntimeMode.HARNESS_FAKE,
        browser_readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=OutlookMonarchSelectorPack(),
        ),
    )
    try:
        result = engine.execute(ToolCall(tool="outlook.mail.list", inputs={"limit": 1}))
        assert result.ok
        env = json.loads((tmp_path / "audit.log").read_text().splitlines()[0])
        assert env["provider"] == "fake_outlook"
        # Profile directory must not have been created — no lifecycle was
        # exercised.
        assert not (tmp_path / "profiles" / "default" / "openclaw.lock").exists()
    finally:
        engine.close()


# --- stdout discipline -----------------------------------------------------


def test_stdout_stays_clean_during_browser_provider_import():
    """Required: importing the BrowserProvider modules must not write to stdout.

    Stdout is reserved for MCP JSON-RPC. Any logging or diagnostic output
    must go to stderr. We re-import to exercise module-load side effects.
    """
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        for module in (
            "openclaw.providers.browser",
            "openclaw.providers.browser_lifecycle",
            "openclaw.providers.outlook",
            "openclaw.providers.outlook.types",
            "openclaw.providers.outlook.page",
            "openclaw.providers.outlook.selectors",
        ):
            if module in sys.modules:
                del sys.modules[module]
        import openclaw.providers.browser  # noqa: F401
        import openclaw.providers.outlook  # noqa: F401
    finally:
        sys.stdout = real_stdout
    assert captured.getvalue() == "", (
        f"browser/outlook imports wrote to stdout: {captured.getvalue()!r}"
    )
