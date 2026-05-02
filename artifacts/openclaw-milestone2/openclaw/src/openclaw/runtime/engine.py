"""OpenClaw runtime engine.

Single entry point for tool execution. All paths — MCP server, harness, CLI
direct calls — go through engine.execute(call), which guarantees:

  - Tool exists in the registry.
  - Input is validated against the tool's schema.
  - Safety Governor classifies and gates.
  - Provider chain is resolved by RuntimeMode (not by registry metadata).
  - Provider Router walks the chain.
  - Envelope is emitted to the audit trace.

Engine.close() propagates close() to every provider — important for the
BrowserProvider's profile lock and Playwright context.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from openclaw.audit.trace import AuditTrace
from openclaw.registry.registry import ToolRegistry
from openclaw.router.router import ProviderRouter
from openclaw.runtime.modes import ChainResolver
from openclaw.safety.governor import SafetyGovernor
from openclaw.types.core import (
    ActionClass,
    ToolCall,
    ToolExecutionEnvelope,
    ToolResult,
)

_log = logging.getLogger("openclaw.engine")


def _redact_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """v0.1 input redactor: keep keys, truncate long string values."""
    out: dict[str, Any] = {}
    for k, v in inputs.items():
        if isinstance(v, str) and len(v) > 64:
            out[k] = v[:64] + "...truncated"
        else:
            out[k] = v
    return out


class OpenClawEngine:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        governor: SafetyGovernor,
        router: ProviderRouter,
        audit: AuditTrace,
        chain_resolver: ChainResolver,
    ) -> None:
        self._registry = registry
        self._governor = governor
        self._router = router
        self._audit = audit
        self._chain_resolver = chain_resolver

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def audit(self) -> AuditTrace:
        return self._audit

    @property
    def router(self) -> ProviderRouter:
        return self._router

    def execute(self, call: ToolCall) -> ToolResult:
        start = datetime.now(timezone.utc)
        t0 = time.monotonic()

        spec = self._registry.get(call.tool)

        provider_used: str | None = None
        attempts = 0
        outcome = "failure"
        error_code: str | None = None
        result_taint = []

        decision = self._governor.evaluate(call.tool, call.inputs, input_taint=[])

        if not decision.allow:
            error_code = (
                decision.error_code.value if decision.error_code else "internal"
            )
            tool_result = ToolResult(
                ok=False,
                error_code=error_code,
                error_message=decision.error_message,
            )
        else:
            assert spec is not None
            chain = self._chain_resolver(call.tool)
            provider_used, attempts, prov_result = self._router.invoke(call, chain)
            if prov_result.ok:
                outcome = "success"
                result_taint = prov_result.taint
                tool_result = ToolResult(
                    ok=True,
                    data=prov_result.data,
                    taint=prov_result.taint,
                )
            else:
                error_code = prov_result.error_code or "internal"
                tool_result = ToolResult(
                    ok=False,
                    error_code=error_code,
                    error_message=prov_result.error_message,
                )

        duration_ms = int((time.monotonic() - t0) * 1000)

        envelope = ToolExecutionEnvelope(
            tool_call_id=call.tool_call_id,
            session_id=call.session_id,
            profile_id=call.profile.profile_id,
            scenario_id=call.scenario_id,
            tool=call.tool,
            tool_version=spec.version if spec else "unknown",
            provider=provider_used,
            provider_attempt=attempts,
            action_class=spec.action_class if spec else ActionClass.READ,
            inputs_redacted=_redact_inputs(call.inputs),
            taint_inputs=[],
            taint_outputs=result_taint,
            requires_approval=decision.requires_approval,
            approval_id=None,
            approval_token_used=None,
            started_at=start,
            duration_ms=duration_ms,
            outcome=outcome,
            error_code=error_code,
            correlation_id=f"cor_{uuid4().hex[:26].upper()}",
        )
        self._audit.append(envelope)
        return tool_result

    def close(self) -> None:
        """Tear down all providers. Safe to call multiple times."""
        for provider_id, provider in self._router.providers.items():
            try:
                provider.close()
            except Exception as exc:  # pragma: no cover
                _log.warning("error closing provider %s: %s", provider_id, exc)
