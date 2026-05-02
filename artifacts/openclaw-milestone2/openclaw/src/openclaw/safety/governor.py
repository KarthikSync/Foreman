"""Safety Governor. Reviewer ordering item #3.

v0.1 skeleton scope:
  - Classify action class.
  - Validate input against the tool's JSON Schema.
  - Refuse destructive actions outright (approval token UX is the next milestone).
  - Refuse hidden primitives unless `primitives_enabled = True`.
  - Implement taint-model skeleton: tainted inputs may not authorize destructive
    actions. (Full taint propagation through the envelope is in §11.2 of the spec
    and tracked via TaintTag objects on ProviderResult.)

The Safety Governor sits between the Tool Registry and the Provider Router.
It cannot be bypassed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jsonschema

from openclaw.registry.registry import ToolRegistry
from openclaw.types.core import ActionClass, TaintTag
from openclaw.types.errors import ErrorCode


@dataclass
class SafetyDecision:
    allow: bool
    error_code: ErrorCode | None = None
    error_message: str | None = None
    requires_approval: bool = False


class SafetyGovernor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        primitives_enabled: bool = False,
    ) -> None:
        self._registry = registry
        self._primitives_enabled = primitives_enabled

    def classify(self, tool_name: str) -> ActionClass | None:
        spec = self._registry.get(tool_name)
        return spec.action_class if spec else None

    def evaluate(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        input_taint: list[TaintTag] | None = None,
    ) -> SafetyDecision:
        input_taint = input_taint or []
        spec = self._registry.get(tool_name)
        if spec is None:
            return SafetyDecision(
                allow=False,
                error_code=ErrorCode.TOOL_NOT_FOUND,
                error_message=f"Unknown tool: {tool_name}",
            )

        # Hidden primitive gate.
        if spec.hidden_by_default and not self._primitives_enabled:
            return SafetyDecision(
                allow=False,
                error_code=ErrorCode.PROVIDER_UNAVAILABLE,
                error_message=f"Tool {tool_name} is gated and not enabled.",
            )

        # JSON Schema input validation.
        try:
            jsonschema.validate(inputs, spec.input_schema)
        except jsonschema.ValidationError as exc:
            return SafetyDecision(
                allow=False,
                error_code=ErrorCode.INVALID_INPUT,
                error_message=f"Input validation failed: {exc.message}",
            )

        # Destructive: refuse outright in v0.1 skeleton — no approval flow yet.
        if spec.action_class == ActionClass.DESTRUCTIVE:
            return SafetyDecision(
                allow=False,
                error_code=ErrorCode.NOT_CONFIRMED,
                error_message=(
                    "Destructive actions require an approval token "
                    "(approval flow not wired in v0.1 skeleton)."
                ),
                requires_approval=True,
            )

        # Taint invariant: tainted content cannot authorize destructive actions.
        # (Read/state calls may legitimately receive tainted IDs; this only fires
        # for destructive tools, which the previous block already rejects in v0.1.
        # The check stays here so the invariant is explicit when v0.2 adds the
        # approval flow.)
        if input_taint and spec.action_class == ActionClass.DESTRUCTIVE:
            return SafetyDecision(
                allow=False,
                error_code=ErrorCode.TAINT_VIOLATION,
                error_message="Tainted content cannot authorize destructive action.",
            )

        return SafetyDecision(allow=True)
