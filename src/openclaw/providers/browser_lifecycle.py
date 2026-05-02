"""Browser lifecycle primitives.

Three responsibilities, deliberately separated from BrowserProvider so each
piece is testable in isolation without Playwright installed:

  - ProfileLock:        atomic exclusive lock over an automation profile dir,
                        with stale-lock recovery (PID-alive + timestamp).
  - resolve_automation_profile_dir: the only sanctioned way to derive a
    profile path; always under <base_dir>/profiles/<profile_id>/.
  - reject_normal_browser_profile: defense-in-depth against accidentally
    pointing OpenClaw at the user's normal Edge/Chrome profile.

Stdout discipline: every diagnostic from this module goes through Python's
`logging` module. Nothing here calls print().
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("openclaw.browser.lifecycle")


# --------------------------------------------------------------------------- #
# Profile path resolution
# --------------------------------------------------------------------------- #

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
    normalized = str(path).replace("\\", "/").lower()
    for marker in _REJECTED_PROFILE_SUBSTRINGS:
        if marker in normalized:
            raise NormalBrowserProfileRejected(
                f"Refusing to use what looks like a normal browser profile: {path}. "
                "OpenClaw must use a dedicated automation profile under "
                "<base_dir>/profiles/<profile_id>/."
            )


def resolve_automation_profile_dir(base_dir: Path, profile_id: str = "default") -> Path:
    if not profile_id or "/" in profile_id or "\\" in profile_id or profile_id.startswith("."):
        raise ValueError(f"Invalid profile_id: {profile_id!r}")
    resolved = (base_dir / "profiles" / profile_id).resolve()
    reject_normal_browser_profile(resolved)
    return resolved


# --------------------------------------------------------------------------- #
# ProfileLock with stale-lock recovery
# --------------------------------------------------------------------------- #


# Lock-file format:
#   line 1: PID
#   line 2: unix timestamp (seconds, float)
# Both lines are produced atomically when the lock is acquired.

_DEFAULT_STALE_AFTER_SECONDS = 24 * 3600.0  # 24 hours


def _pid_alive(pid: int) -> bool | None:
    """True if the PID is alive, False if not, None if undecidable.

    POSIX: `os.kill(pid, 0)` raises ProcessLookupError when no such process
    exists, PermissionError when the process exists but is owned by another
    user, and otherwise returns silently.

    Windows: `os.kill` exists but its semantics differ. We return None on
    OSError so the caller falls back to timestamp-based staleness.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _is_lock_stale(
    lock_path: Path,
    *,
    stale_after_seconds: float = _DEFAULT_STALE_AFTER_SECONDS,
) -> bool:
    """Inspect the lock file and decide if it is stale enough to reclaim."""
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False  # cannot read; safer to assume held

    parts = raw.strip().split("\n", 1)
    pid_str = parts[0].strip()

    try:
        pid = int(pid_str)
    except ValueError:
        return False  # malformed; assume held

    alive = _pid_alive(pid)
    if alive is False:
        return True
    if alive is True:
        return False
    # alive is None — fall through to timestamp staleness.

    if len(parts) >= 2:
        try:
            ts = float(parts[1].strip())
        except ValueError:
            return False
        if (time.time() - ts) > stale_after_seconds:
            return True

    return False


class ProfileLockContended(RuntimeError):
    """Another process / instance already holds this profile's lock."""


@dataclass
class ProfileLock:
    """File-based exclusive lock over a single automation profile directory.

    Backed by an O_CREAT | O_EXCL file at `<profile_dir>/openclaw.lock`. The
    file contains the holder's PID on line 1 and a unix timestamp on line 2.

    On acquire failure, the lock file is inspected:
      - If the PID is no longer alive → recover (delete and retry).
      - If the PID's status is undecidable (Windows) and the timestamp is
        older than `stale_after_seconds` → recover.
      - Otherwise → raise ProfileLockContended.
    """

    profile_dir: Path
    stale_after_seconds: float = _DEFAULT_STALE_AFTER_SECONDS

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

        if self._try_create():
            return

        # Acquire failed. Check for staleness and try to recover.
        if _is_lock_stale(self.lock_path, stale_after_seconds=self.stale_after_seconds):
            _log.warning(
                "recovering stale profile lock at %s (previous holder is no longer alive)",
                self.lock_path,
            )
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
            if self._try_create():
                return
            # Race: someone else won during recovery.

        raise ProfileLockContended(
            f"Profile lock already held: {self.lock_path}. "
            "Another OpenClaw process is using this profile."
        )

    def _try_create(self) -> bool:
        try:
            fd = os.open(
                str(self.lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            return False
        try:
            content = f"{os.getpid()}\n{time.time():.6f}\n"
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)
        self._held = True
        _log.info("acquired profile lock at %s", self.lock_path)
        return True

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
