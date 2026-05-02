"""Browser lifecycle tests — milestone (1) acceptance criteria."""

from __future__ import annotations

import os
import sys
import tempfile
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
    # Should not raise.
    reject_normal_browser_profile(tmp_path / "profiles" / "default")


# --- ProfileLock ------------------------------------------------------------


def test_profile_dir_is_created_under_openclaw_home_when_lock_acquired(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "default"
    assert not profile_dir.exists()

    lock = ProfileLock(profile_dir)
    lock.acquire()
    try:
        assert profile_dir.exists()
        assert profile_dir.is_dir()
        assert lock.lock_path.exists()
        assert lock.lock_path.read_text().strip() == str(os.getpid())
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
    assert lock.lock_path.exists()

    lock.release()
    assert not lock.held
    assert not lock.lock_path.exists()

    # And it can be re-acquired.
    lock.acquire()
    assert lock.held
    lock.release()


def test_lock_context_manager_releases_on_exit(tmp_path: Path):
    profile_dir = tmp_path / "profiles" / "default"
    with ProfileLock(profile_dir) as lock:
        assert lock.held
    assert not lock.held
    assert not (profile_dir / "openclaw.lock").exists()


def test_lock_release_is_idempotent(tmp_path: Path):
    lock = ProfileLock(tmp_path / "profiles" / "default")
    lock.release()  # not held; no error
    lock.acquire()
    lock.release()
    lock.release()  # idempotent


# --- BrowserProvider laziness ----------------------------------------------


def test_ensure_context_is_lazy_construction_does_no_filesystem_work(tmp_path: Path):
    """Constructing BrowserProvider must not create the profile dir or lock.

    Lifecycle is opt-in via _ensure_profile_acquired() / _ensure_context().
    """
    readiness = BrowserReadiness(
        enabled=True,
        profile_id="default",
        base_dir=tmp_path,
    )
    provider = BrowserProvider(readiness=readiness)

    profile_dir = tmp_path / "profiles" / "default"
    assert not profile_dir.exists(), "construction must not create profile dir"
    assert not (profile_dir / "openclaw.lock").exists()

    # The lock object exists but is not held.
    assert provider._lock is not None
    assert not provider._lock.held


def test_ensure_profile_acquired_is_idempotent(tmp_path: Path):
    readiness = BrowserReadiness(enabled=True, base_dir=tmp_path)
    provider = BrowserProvider(readiness=readiness)
    try:
        provider._ensure_profile_acquired()
        assert provider._lock.held
        # Calling again should not double-acquire or raise.
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
    provider.close()  # second close must not raise


def test_disabled_provider_has_no_lock(tmp_path: Path):
    """When readiness.enabled=False, no profile dir is resolved and no lock exists."""
    provider = BrowserProvider(readiness=BrowserReadiness(enabled=False))
    assert provider._lock is None
    assert provider._profile_dir is None


def test_enabled_provider_rejects_normal_browser_profile_at_construction(tmp_path: Path):
    """Path validation runs at construction; the provider cannot hold a
    BrowserReadiness pointing inside the user's normal Edge/Chrome profile.
    """
    bad_base = Path("/home/me/.config/google-chrome")
    readiness = BrowserReadiness(enabled=True, base_dir=bad_base)
    with pytest.raises(NormalBrowserProfileRejected):
        BrowserProvider(readiness=readiness)


# --- stdout discipline (browser-side) --------------------------------------


def test_browser_logs_do_not_write_stdout(tmp_path: Path, capsys):
    """Acquire a lock and close the provider — neither path may write to stdout."""
    readiness = BrowserReadiness(enabled=True, base_dir=tmp_path)
    provider = BrowserProvider(readiness=readiness)
    try:
        provider._ensure_profile_acquired()
    finally:
        provider.close()

    captured = capsys.readouterr()
    assert captured.out == "", (
        f"BrowserProvider wrote to stdout: {captured.out!r} "
        "(stdout is reserved for MCP JSON-RPC)"
    )


# --- integration: SERVE_LOCAL still refuses Outlook until a pack ships ------


def test_serve_local_outlook_still_provider_unavailable_until_selector_pack_loaded(
    tmp_path: Path,
):
    """Even with browser fully enabled and the lock acquirable, an Outlook
    call in SERVE_LOCAL must return provider_unavailable because no
    SelectorPack ships in milestone (1).
    """
    from openclaw.runtime.bootstrap import build_engine
    from openclaw.runtime.modes import RuntimeMode
    from openclaw.types.core import ToolCall

    engine = build_engine(
        base_dir=tmp_path,
        mode=RuntimeMode.SERVE_LOCAL,
        browser_readiness=BrowserReadiness(
            enabled=True,
            base_dir=tmp_path,
            selector_pack=None,  # explicitly: no pack
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
