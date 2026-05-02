"""Bootstrap. Assembles a runtime instance ready to serve tool calls.

Mode is required:

  RuntimeMode.SERVE_LOCAL     - MCP serve against real surfaces
  RuntimeMode.HARNESS_FAKE    - harness against deterministic fakes
  RuntimeMode.HARNESS_LIVE    - harness against real surfaces

Browser readiness defaults to disabled. Opt in by passing a BrowserReadiness
with `enabled=True`. The bootstrap injects `base_dir` if not set, so the
profile path is always derived from `<base_dir>/profiles/<profile_id>/`.
Callers cannot point at the user's normal browser profile.

Lifecycle: callers SHOULD call `engine.close()` at process shutdown to
release the browser profile lock and tear down Playwright cleanly.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from openclaw.audit.trace import AuditTrace
from openclaw.memory.store import MemoryStore
from openclaw.providers.browser import BrowserProvider, BrowserReadiness
from openclaw.providers.fake_outlook import FakeOutlookProvider
from openclaw.providers.memory import MemoryProvider
from openclaw.registry.registry import default_registry
from openclaw.router.router import ProviderRouter
from openclaw.runtime.engine import OpenClawEngine
from openclaw.runtime.modes import RuntimeMode, make_resolver
from openclaw.safety.governor import SafetyGovernor


def build_engine(
    *,
    base_dir: Path,
    mode: RuntimeMode,
    primitives_enabled: bool = False,
    browser_readiness: BrowserReadiness | None = None,
) -> OpenClawEngine:
    base_dir.mkdir(parents=True, exist_ok=True)

    registry = default_registry()
    governor = SafetyGovernor(registry, primitives_enabled=primitives_enabled)
    audit = AuditTrace(base_dir / "audit.log")
    memory = MemoryStore(base_dir / "openclaw.db")

    if browser_readiness is None:
        browser_readiness = BrowserReadiness(enabled=False)
    elif browser_readiness.enabled and browser_readiness.base_dir is None:
        # Force base_dir to ours so the path always resolves under our control.
        browser_readiness = replace(browser_readiness, base_dir=base_dir)

    providers = {
        "fake_outlook": FakeOutlookProvider(),
        "memory": MemoryProvider(memory),
        "browser": BrowserProvider(readiness=browser_readiness),
    }
    router = ProviderRouter(providers)
    chain_resolver = make_resolver(mode)

    return OpenClawEngine(
        registry=registry,
        governor=governor,
        router=router,
        audit=audit,
        chain_resolver=chain_resolver,
    )
