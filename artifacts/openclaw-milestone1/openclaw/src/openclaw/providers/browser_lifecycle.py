"""Browser lifecycle primitives.

Three responsibilities, deliberately separated from BrowserProvider so each
piece is testable in isolation without Playwright installed:

  - ProfileLock:        atomic exclusive lock over an automation profile dir.
  - resolve_automation_profile_dir: the only sanctioned way to derive a
    profile path; always under <base_dir>/profiles/<profile_id>/.
  - reject_normal_browser_profile: defense-in-depth against accidentally
    pointing OpenClaw at the user's normal Edge/Chrome profile (which
    Playwright also warns against).

Stdout discipline: every diagnostic from this module goes through Python's
`logging` module, which is configured at process start to write to stderr
only. Nothing here calls print().
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger("openclaw.browser.lifecycle")


# --------------------------------------------------------------------------- #
# Profile path resolution
# --------------------------------------------------------------------------- #

# Substrings that indicate a user's normal browser profile location. The match
# is case-insensitive and uses forward slashes after normalization.
_REJECTED_PROFILE_SUBSTRINGS: tuple[str, ...] = (
    "microsoft/edge/user data",
    "google/chrome/user data",
    "chromium/user data",
    "library/application support/google/chrome",
    "library/application support/microsoft edge",
    "library/application support/chromium",
    ".config/google-chrome",
    ".config/microsoft-edge",
    ".config/chromium",
)


class NormalBrowserProfileRejected(ValueError):
    """Raised when a path looks like the user's normal browser profile."""


def reject_normal_browser_profile(path: Path) -> None:
    """Raise if `path` matches a known user-browser profile location.

    Playwright's documentation explicitly warns against automating the user's
    normal Chrome profile and recommends a separate automation directory.
    OpenClaw enforces this at the lifecycle layer rather than relying on
    discipline at call sites.
    """
    normalized = str(path).replace("\\", "/").lower()
    for marker in _REJECTED_PROFILE_SUBSTRINGS:
        if marker in normalized:
            raise NormalBrowserProfileRejected(
                f"Refusing to use what looks like a normal browser profile: {path}. "
                "OpenClaw must use a dedicated automation profile under "
                "<base_dir>/profiles/<profile_id>/."
            )


def resolve_automation_profile_dir(base_dir: Path, profile_id: str = "default") -> Path:
    """Return the dedicated automation profile directory for `profile_id`.

    Always under `<base_dir>/profiles/<profile_id>/`. Callers cannot override
    this — the path is derived, not configured.
    """
    if not profile_id or "/" in profile_id or "\\" in profile_id or profile_id.startswith("."):
        raise ValueError(f"Invalid profile_id: {profile_id!r}")
    resolved = (base_dir / "profiles" / profile_id).resolve()
    reject_normal_browser_profile(resolved)
    return resolved


# --------------------------------------------------------------------------- #
# ProfileLock
# --------------------------------------------------------------------------- #


class ProfileLockContended(RuntimeError):
    """Another process / instance already holds this profile's lock."""


@dataclass
class ProfileLock:
    """File-based exclusive lock over a single automation profile directory.

    Backed by an O_CREAT | O_EXCL file at `<profile_dir>/openclaw.lock`. This
    is intentionally simpler than a true OS lock — Playwright itself enforces
    single-context-per-user-data-dir at the OS level, so this lock is mainly
    a clear, early error message and stale-instance detection.

    NOT a stale-lock recoverer in v0.1 — if a previous process died holding
    the lock, the user must remove the lock file manually. Stale recovery is
    on the roadmap.
    """

    profile_dir: Path

    def __post_init__(self) -> None:
        self._held: bool = False

    @property
    def lock_path(self) -> Path:
        return self.profile_dir / "openclaw.lock"

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> None:
        if self._held:
            raise RuntimeError(
                f"Profile lock {self.lock_path} already held by this instance"
            )
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(
                str(self.lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            raise ProfileLockContended(
                f"Profile lock already held: {self.lock_path}. "
                "Another OpenClaw process is using this profile, or a stale "
                "lock file remains from a crashed previous run."
            ) from exc
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        self._held = True
        _log.info("acquired profile lock at %s", self.lock_path)

    def release(self) -> None:
        if not self._held:
            return
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass
        self._held = False
        _log.info("released profile lock at %s", self.lock_path)

    def __enter__(self) -> "ProfileLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()
