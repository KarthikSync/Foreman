"""Runtime modes and per-mode provider chain resolution.

The Tool Registry declares tool metadata (name, action class, schema). The
provider chain is resolved separately, by runtime mode. This prevents the
fake harness provider from leaking into the production serve path — a
hardcoded chain like ("fake_outlook", "browser") would do exactly that.

Modes:
  SERVE_LOCAL    — MCP stdio serve. Uses production providers (browser, memory).
  HARNESS_FAKE   — Harness against deterministic fakes. Uses fake_outlook.
  HARNESS_LIVE   — Harness against real surfaces. Uses production providers.

Per-mode chain maps are explicit and grep-able. A new tool must be added in
all three maps before it can be invoked, by design — silence is a refusal.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable


class RuntimeMode(str, Enum):
    SERVE_LOCAL = "serve_local"
    HARNESS_FAKE = "harness_fake"
    HARNESS_LIVE = "harness_live"


# Per-mode chain map. Keep the keys identical across modes so cross-mode
# diffs are easy to read; an empty tuple means "tool is not available in
# this mode."
PROVIDER_CHAINS: dict[RuntimeMode, dict[str, tuple[str, ...]]] = {
    RuntimeMode.SERVE_LOCAL: {
        "outlook.mail.list": ("browser",),
        "outlook.mail.read": ("browser",),
        "memory.preferences.get": ("memory",),
        "memory.preferences.set": ("memory",),
        "browser.click": ("browser",),
    },
    RuntimeMode.HARNESS_FAKE: {
        "outlook.mail.list": ("fake_outlook",),
        "outlook.mail.read": ("fake_outlook",),
        "memory.preferences.get": ("memory",),
        "memory.preferences.set": ("memory",),
        # browser.click stays browser-routed; the fake harness never touches it
        # because primitives are gated by the Safety Governor.
        "browser.click": ("browser",),
    },
    RuntimeMode.HARNESS_LIVE: {
        "outlook.mail.list": ("browser",),
        "outlook.mail.read": ("browser",),
        "memory.preferences.get": ("memory",),
        "memory.preferences.set": ("memory",),
        "browser.click": ("browser",),
    },
}


ChainResolver = Callable[[str], tuple[str, ...]]


def make_resolver(
    mode: RuntimeMode,
    chains: dict[RuntimeMode, dict[str, tuple[str, ...]]] | None = None,
) -> ChainResolver:
    """Return a resolver function bound to the given mode."""
    table = (chains or PROVIDER_CHAINS)[mode]

    def resolve(tool_name: str) -> tuple[str, ...]:
        return table.get(tool_name, ())

    return resolve
