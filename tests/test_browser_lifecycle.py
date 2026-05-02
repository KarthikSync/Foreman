"""Browser lifecycle tests — milestone (1) + milestone (2) stale-lock recovery."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from openclaw.providers.browser import BrowserProvider, BrowserReadiness
from openclaw.providers.browser_lifecycle import (
    NormalBrowserProfileRejected,
    ProfileLock,
    ProfileLockContended,
    reject_normal_browser_profile,
    resolve_automation_profile_dir,
)
from openclaw.providers.outlook import OutlookMonarchSelectorPack


# --- profile path resolution ------------------------------------------------


def test_resolve_profile_dir_under_base_dir(tmp_path: Path):
    p = resolve_automation_profile_dir(tmp_path, "default")
    assert p == (tmp_path / "profiles" / "default").resolve()


def test_resolve_rejects_invalid_profile_id(tmp_path: Path):
    for bad in ("", "../escape", "with/slash", "with\\back", ".hidden"):
        with pytest.raises(ValueError):
            resolve_automation_profile_dir(tmp_path, bad)


# --- normal browser profile rejection ---------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "/Users/me/Library/Application Support/Google/Chrome/Default",
        "/Users/me/Library/Application Support/Microsoft Edge/Default",
        "/home/me/.config/google-chrome/Default",
        "/home/me/.config/microsoft-edge/Default",
        "/home/me/.config/chromium/Default",
        "C:/Users/me/AppData/Local/Microsoft/Edge/User Data",
        "C:/Users/me/AppData/Local/Google/Chrome/User Data",
        "C:\\Users\\me\\AppData\\Local\\Google\\Chrome\\User Data",
    ],
)
def test_normal_browser_profile_path_is_rejected(bad_path: str):
    with pytest.raises(NormalBrowserProfileRejected):
        reject_normal_browser_profile(Path(bad_path))


def test_clean_automation_profile_path_is_accepted(tmp_path: Path):
    reject_normal_browser_profile(tmp_path / "profiles" / "default")


# --- ProfileLock basics -----------------------------------------------------


def test_profile_dir_is_created_under_openclaw_home_when_lock_acquired(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "default"
    assert not profile_dir.exists()

    lock = ProfileLock(profile_dir)
    lock.acquire()
    try:
        assert profile_dir.exists()
        assert profile_dir.is_dir()
        assert lock.lock_path.exists()
        # Lock contents now have PID + timestamp on separate lines.
        contents = lock.lock_path.read_text().strip().split("\n")
        assert int(contents[0]) == os.getpid()
        assert float(contents[1]) > 0
    finally:
        lock.release()


def test_second_context_same_profile_fails_lock(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "default"

    lock_a = ProfileLock(profile_dir)
    lock_a.acquire()
    try:
        lock_b = ProfileLock(profile_dir)
        with pytest.raises(ProfileLockContended):
            lock_b.acquire()
        assert not lock_b.held
    finally:
        lock_a.release()


def test_lock_released_on_close(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "default"

    lock = ProfileLock(profile_dir)
    lock.acquire()
    assert lock.held
    lock.release()
    assert not lock.held
    assert not lock.lock_path.exists()

    lock.acquire()
    assert lock.held
    lock.release()


def test_lock_context_manager_releases_on_exit(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "default"
    with ProfileLock(profile_dir) as lock:
        assert lock.held
    assert not lock.held


def test_lock_release_is_idempotent(tmp_path: Path):
    lock = ProfileLock(tmp_path / "profiles" / "default")
    lock.release()
    lock.acquire()
    lock.release()
    lock.release()


# --- Stale lock recovery (milestone 2 improvement) -------------------------


def test_stale_lock_with_dead_pid_is_recovered(tmp_path: Path):
    """A lock file naming a dead PID is treated as stale and reclaimed."""
    profile_dir = tmp_path / "profiles" / "default"
    profile_dir.mkdir(parents=True)
    # Write a lock pointing at PID 1 (init/launchd) — alive — should NOT be
    # treated as stale. Then overwrite with a clearly dead PID.
    lock_path = profile_dir / "openclaw.lock"

    # Use a high PID that is essentially guaranteed not to exist.
    # On Linux, max PID is configurable but 99999999 is well above default.
    dead_pid = 99999999
    lock_path.write_text(f"{dead_pid}\n{time.time():.6f}\n")

    new_lock = ProfileLock(profile_dir)
    # Should reclaim instead of raising.
    new_lock.acquire()
    try:
        assert new_lock.held
        # Lock file now reflects our PID.
        first_line = lock_path.read_text().split("\n")[0]
        assert int(first_line) == os.getpid()
    finally:
        new_lock.release()


def test_alive_pid_lock_is_not_recovered(tmp_path: Path):
    """A lock naming the current process must not be treated as stale."""
    profile_dir = tmp_path / "profiles" / "default"
    profile_dir.mkdir(parents=True)
    lock_path = profile_dir / "openclaw.lock"
    # Write a lock pointing at OUR PID — definitely alive.
    lock_path.write_text(f"{os.getpid()}\n{time.time():.6f}\n")

    new_lock = ProfileLock(profile_dir)
    with pytest.raises(ProfileLockContended):
        new_lock.acquire()


def test_malformed_lock_file_is_not_recovered(tmp_path: Path):
    """A lock file with garbage content is treated as held (defensive)."""
    profile_dir = tmp_path / "profiles" / "default"
    profile_dir.mkdir(parents=True)
    lock_path = profile_dir / "openclaw.lock"
    lock_path.write_text("not-a-pid\n")

    new_lock = ProfileLock(profile_dir)
    with pytest.raises(ProfileLockContended):
        new_lock.acquire()


# --- BrowserProvider laziness ----------------------------------------------


def test_ensure_context_is_lazy_construction_does_no_filesystem_work(tmp_path: Path):
    readiness = BrowserReadiness(
        enabled=True,
        profile_id="default",
        base_dir=tmp_path,
    )
    provider = BrowserProvider(readiness=readiness)

    profile_dir = tmp_path / "profiles" / "default"
    assert not profile_dir.exists()
    assert provider._lock is not None
    assert not provider._lock.held


def test_ensure_profile_acquired_is_idempotent(tmp_path: Path):
    readiness = BrowserReadiness(enabled=True, base_dir=tmp_path)
    provider = BrowserProvider(readiness=readiness)
    try:
        provider._ensure_profile_acquired()
        assert provider._lock.held
        provider._ensure_profile_acquired()
        assert provider._lock.held
    finally:
        provider.close()


def test_provider_close_releases_lock(tmp_path: Path):
    readiness = BrowserReadiness(enabled=True, base_dir=tmp_path)
    provider = BrowserProvider(readiness=readiness)
    provider._ensure_profile_acquired()
    assert provider._lock.held

    provider.close()
    assert not provider._lock.held
    assert not (tmp_path / "profiles" / "default" / "openclaw.lock").exists()


def test_provider_close_is_idempotent(tmp_path: Path):
    readiness = BrowserReadiness(enabled=True, base_dir=tmp_path)
    provider = BrowserProvider(readiness=readiness)
    provider._ensure_profile_acquired()
    provider.close()
    provider.close()


def test_disabled_provider_has_no_lock():
    provider = BrowserProvider(readiness=BrowserReadiness(enabled=False))
    assert provider._lock is None
    assert provider._profile_dir is None


def test_enabled_provider_rejects_normal_browser_profile_at_construction(tmp_path: Path):
    bad_base = Path("/home/me/.config/google-chrome")
    readiness = BrowserReadiness(enabled=True, base_dir=bad_base)
    with pytest.raises(NormalBrowserProfileRejected):
        BrowserProvider(readiness=readiness)


def test_browser_logs_do_not_write_stdout(tmp_path: Path, capsys):
    readiness = BrowserReadiness(enabled=True, base_dir=tmp_path)
    provider = BrowserProvider(readiness=readiness)
    try:
        provider._ensure_profile_acquired()
    finally:
        provider.close()

    captured = capsys.readouterr()
    assert captured.out == "", (
        f"BrowserProvider wrote to stdout: {captured.out!r}"
    )


def test_serve_local_outlook_still_provider_unavailable_until_selector_pack_loaded(
    tmp_path: Path,
):
    from openclaw.runtime.bootstrap import build_engine
    from openclaw.runtime.modes import RuntimeMode
    from openclaw.types.core import ToolCall

    engine = build_engine(
        base_dir=tmp_path,
        mode=RuntimeMode.SERVE_LOCAL,
        browser_readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=None,
        ),
    )
    try:
        result = engine.execute(
            ToolCall(tool="outlook.mail.list", inputs={"limit": 1})
        )
        assert not result.ok
        assert result.error_code == "provider_unavailable"
    finally:
        engine.close()
