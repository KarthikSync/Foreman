"""BrowserProvider — Playwright-backed provider with selector-pack dispatch.

Milestone (2): outlook.mail.list is wired through OutlookMonarchSelectorPack.
Other tools still return provider_unavailable.

Key seams:
  - `_page_factory_for_test`: optional callable that returns an OutlookPage.
    Production code does not pass this; tests inject a FakeOutlookPage to
    exercise dispatch without launching Playwright.
  - `_ensure_context()`: lazy. Called only when invoke() actually needs a
    page and no test factory was supplied.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from openclaw.providers.base import Provider
from openclaw.providers.browser_lifecycle import (
    ProfileLock,
    ProfileLockContended,
    resolve_automation_profile_dir,
)
from openclaw.providers.outlook import (
    NeedsInteractiveLogin,
    OutlookMonarchSelectorPack,
    OutlookPage,
    PlaywrightOutlookPage,
    UIVariantUnsupported,
    to_taint_tags,
)
from openclaw.providers.selector_pack import SelectorPack
from openclaw.types.core import ProfileContext, ProviderResult, ToolCall

_log = logging.getLogger("openclaw.browser")


@dataclass
class BrowserReadiness:
    """Declarative readiness for the BrowserProvider.

    Defaults to disabled. The runtime owner opts in by setting `enabled=True`
    and supplying a SelectorPack. The profile path is derived from
    `<base_dir>/profiles/<profile_id>/`; callers cannot override it.
    """

    enabled: bool = False
    profile_id: str = "default"
    base_dir: Path | None = None
    selector_pack: SelectorPack | None = None
    headless: bool = False  # dev default headed; production toggles later


class BrowserProvider(Provider):
    def __init__(
        self,
        *,
        readiness: BrowserReadiness | None = None,
        _page_factory_for_test: Callable[[], OutlookPage] | None = None,
    ) -> None:
        self._readiness = readiness or BrowserReadiness()
        self._profile_dir: Path | None = None
        self._lock: ProfileLock | None = None
        self._pw: Any = None
        self._context: Any = None
        self._outlook_page: OutlookPage | None = None
        self._page_factory_for_test = _page_factory_for_test

        # Resolve and validate profile directory at construction.
        if self._readiness.enabled and self._readiness.base_dir is not None:
            self._profile_dir = resolve_automation_profile_dir(
                self._readiness.base_dir,
                self._readiness.profile_id,
            )
            self._lock = ProfileLock(self._profile_dir)

    # -- Provider interface ---------------------------------------------------

    @property
    def provider_id(self) -> str:
        return "browser"

    def supports(self, tool_name: str, profile: ProfileContext) -> bool:
        r = self._readiness
        if not r.enabled:
            return False
        if r.selector_pack is None:
            return False
        if not r.selector_pack.supports(tool_name):
            return False
        # When a test page factory is wired, we do not require a profile_dir
        # because the lock/Playwright path is bypassed.
        if self._page_factory_for_test is None and self._profile_dir is None:
            return False
        return True

    def invoke(self, call: ToolCall) -> ProviderResult:
        if call.tool == "outlook.mail.list":
            return self._invoke_outlook_mail_list(call)
        return ProviderResult(
            ok=False,
            error_code="provider_unavailable",
            error_message=f"BrowserProvider does not implement {call.tool} in v0.1.",
        )

    # -- Tool implementations -------------------------------------------------

    def _invoke_outlook_mail_list(self, call: ToolCall) -> ProviderResult:
        pack = self._readiness.selector_pack
        if pack is None or not isinstance(pack, OutlookMonarchSelectorPack):
            return ProviderResult(
                ok=False,
                error_code="provider_unavailable",
                error_message="No Outlook Monarch selector pack configured.",
            )

        try:
            page = self._get_outlook_page()
        except ProfileLockContended as exc:
            return ProviderResult(
                ok=False,
                error_code="provider_unavailable",
                error_message=f"profile lock contended: {exc}",
                terminal=True,
            )
        except RuntimeError as exc:
            return ProviderResult(
                ok=False,
                error_code="provider_unavailable",
                error_message=str(exc),
            )
        except Exception as exc:
            # Catches Playwright's Error class and any other unexpected failure
            # in the launch path. The full traceback is logged to stderr; the
            # envelope captures the error code and a one-line message.
            _log.exception("BrowserProvider._get_outlook_page failed")
            return ProviderResult(
                ok=False,
                error_code="provider_unavailable",
                error_message=f"browser launch failed: {exc.__class__.__name__}: {exc}",
            )

        try:
            messages = pack.list_messages(
                page,
                limit=call.inputs.get("limit", 25),
                unread_only=call.inputs.get("unread_only", False),
            )
        except NeedsInteractiveLogin as exc:
            return ProviderResult(
                ok=False,
                error_code="needs_interactive_login",
                error_message=str(exc),
                terminal=True,
            )
        except UIVariantUnsupported as exc:
            return ProviderResult(
                ok=False,
                error_code="ui_variant_unsupported",
                error_message=str(exc),
                terminal=True,
            )

        data = {"messages": [m.to_dict() for m in messages]}
        taint = to_taint_tags(messages)
        return ProviderResult(ok=True, data=data, taint=taint)

    # -- Page acquisition -----------------------------------------------------

    def _get_outlook_page(self) -> OutlookPage:
        """Return an OutlookPage, launching Playwright if needed."""
        if self._page_factory_for_test is not None:
            # Test seam: do not touch the lock or Playwright.
            return self._page_factory_for_test()
        if self._outlook_page is not None:
            return self._outlook_page
        self._ensure_context()
        # In production, the freshly launched persistent context's first page
        # is wrapped as an OutlookPage. Navigation to outlook.office.com is
        # the responsibility of the lifecycle (or a caller-provided
        # navigation step). v0.1 milestone (2) wires the wrapping; navigation
        # is an explicit followup before live runs.
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._outlook_page = PlaywrightOutlookPage(page)
        return self._outlook_page

    # -- Lifecycle ------------------------------------------------------------

    def _ensure_profile_acquired(self) -> Path:
        if self._lock is None or self._profile_dir is None:
            raise RuntimeError(
                "BrowserProvider not configured with an enabled readiness; "
                "cannot acquire profile."
            )
        if not self._lock.held:
            self._lock.acquire()
        return self._profile_dir

    def _launch_browser_context(self) -> Any:
        if self._lock is None or not self._lock.held:
            raise RuntimeError(
                "Cannot launch browser without an acquired profile lock."
            )
        if self._context is not None:
            return self._context

        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Playwright is not installed. Install with "
                "`pip install openclaw[browser]` and run "
                "`python -m playwright install msedge`."
            ) from exc

        _log.info(
            "launching persistent context (profile=%s, headless=%s)",
            self._readiness.profile_id,
            self._readiness.headless,
        )
        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            channel="msedge",
            headless=self._readiness.headless,
        )
        return self._context

    def _ensure_context(self) -> Any:
        self._ensure_profile_acquired()
        return self._launch_browser_context()

    def close(self) -> None:
        self._outlook_page = None
        if self._context is not None:
            try:
                self._context.close()
            except Exception as exc:  # pragma: no cover
                _log.warning("error closing browser context: %s", exc)
            self._context = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception as exc:  # pragma: no cover
                _log.warning("error stopping playwright: %s", exc)
            self._pw = None
        if self._lock is not None and self._lock.held:
            self._lock.release()
