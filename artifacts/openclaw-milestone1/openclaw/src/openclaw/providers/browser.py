"""BrowserProvider — live Playwright provider.

Milestone (1) scope: persistent context plumbing, no selectors.

  - Profile path is resolved at construction (no filesystem changes yet).
  - `_ensure_profile_acquired()` creates the dir and acquires the lock; no
    Playwright import. Idempotent and testable without Playwright installed.
  - `_launch_browser_context()` is the Playwright-touching step. Lazy-imports
    Playwright; raises a clear error if not installed.
  - `_ensure_context()` composes the two; called by invoke().
  - `close()` releases everything in reverse order.
  - Logging goes through Python's `logging` module which is configured to
    stderr only by `mcp_server/server.py`. Nothing here calls print().

`supports()` reports declarative readiness: enabled + profile_dir resolved +
selector_pack present + tool in pack. The lock and Playwright launch are
runtime concerns checked at invoke() time, where they can fail with a
specific error_code instead of a stale "supports=False" lie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openclaw.providers.base import Provider
from openclaw.providers.browser_lifecycle import (
    ProfileLock,
    resolve_automation_profile_dir,
)
from openclaw.types.core import ProfileContext, ProviderResult, ToolCall

_log = logging.getLogger("openclaw.browser")


@dataclass(frozen=True)
class SelectorPack:
    """A selector pack covers a set of tools for a known UI variant."""

    name: str  # e.g. "outlook_monarch_2026_q1"
    supported_tools: frozenset[str]


@dataclass
class BrowserReadiness:
    """Declarative readiness for the BrowserProvider.

    The runtime owner declares intent. The provider resolves the profile
    directory from `base_dir + profile_id` at construction; lock acquisition
    and Playwright launch happen lazily.

    Defaults to disabled so BrowserProvider.supports() returns False unless
    the runtime owner explicitly opts in.
    """

    enabled: bool = False
    profile_id: str = "default"
    base_dir: Path | None = None
    selector_pack: SelectorPack | None = None
    headless: bool = False  # dev default headed; production will toggle later


class BrowserProvider(Provider):
    def __init__(self, *, readiness: BrowserReadiness | None = None) -> None:
        self._readiness = readiness or BrowserReadiness()
        self._profile_dir: Path | None = None
        self._lock: ProfileLock | None = None
        # Playwright handles, populated by _launch_browser_context.
        self._pw: Any = None
        self._context: Any = None

        # Resolve the profile directory at construction. This validates the
        # path (rejects normal browser profiles) but does NOT create it.
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
        if self._profile_dir is None:
            return False
        if r.selector_pack is None:
            return False
        if tool_name not in r.selector_pack.supported_tools:
            return False
        return True

    def invoke(self, call: ToolCall) -> ProviderResult:
        # Milestone (1): persistent-context plumbing is implemented but is
        # NOT exercised via invoke(). The lifecycle is reachable via the
        # private _ensure_profile_acquired / _ensure_context methods (and
        # tested directly there); the real browser launch only fires once a
        # selector implementation lands in the next milestone.
        return ProviderResult(
            ok=False,
            error_code="provider_unavailable",
            error_message=(
                "BrowserProvider lifecycle is wired but no selector "
                "implementation ships in milestone (1)."
            ),
        )

    # -- Lifecycle ------------------------------------------------------------

    def _ensure_profile_acquired(self) -> Path:
        """Create the profile dir and acquire the lock. No Playwright."""
        if self._lock is None or self._profile_dir is None:
            raise RuntimeError(
                "BrowserProvider not configured with an enabled readiness; "
                "cannot acquire profile."
            )
        if not self._lock.held:
            self._lock.acquire()
        return self._profile_dir

    def _launch_browser_context(self) -> Any:
        """Launch Playwright persistent context against the locked profile.

        Lazy-imports Playwright. Raises RuntimeError with a clear message if
        Playwright is not installed. Does not navigate anywhere.
        """
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
        """Acquire profile + launch context. Lazy and idempotent."""
        self._ensure_profile_acquired()
        return self._launch_browser_context()

    def close(self) -> None:
        """Tear down in reverse order. Safe to call multiple times."""
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
