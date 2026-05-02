"""Tool Registry. Reviewer ordering item #2.

Hardcoded initial catalog matching spec §18. Tool metadata only. The provider
chain for each tool is resolved separately, per runtime mode, by
`openclaw.runtime.modes.make_resolver`. This separation prevents the fake
harness provider from being routable in production.

Primitives are registered but hidden by default — they only surface in
tools/list when primitives_enabled=True.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openclaw.types.core import ActionClass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    action_class: ActionClass
    description: str
    input_schema: dict[str, Any]
    hidden_by_default: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_visible(self, primitives_enabled: bool = False) -> list[ToolSpec]:
        return [
            spec
            for spec in self._tools.values()
            if not spec.hidden_by_default or primitives_enabled
        ]

    def list_all(self) -> list[ToolSpec]:
        return list(self._tools.values())


def default_registry() -> ToolRegistry:
    """Build the v0.1 minimal catalog. Provider chains are NOT declared here."""
    reg = ToolRegistry()

    reg.register(
        ToolSpec(
            name="outlook.mail.list",
            version="1",
            action_class=ActionClass.READ,
            description="List messages from the user's Outlook inbox.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 25,
                    },
                    "unread_only": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        )
    )

    reg.register(
        ToolSpec(
            name="outlook.mail.read",
            version="1",
            action_class=ActionClass.READ,
            description="Read the body and headers of a single Outlook message.",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "additionalProperties": False,
            },
        )
    )

    reg.register(
        ToolSpec(
            name="memory.preferences.get",
            version="1",
            action_class=ActionClass.READ,
            description="Read a stored user preference.",
            input_schema={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
                "additionalProperties": False,
            },
        )
    )

    reg.register(
        ToolSpec(
            name="memory.preferences.set",
            version="1",
            action_class=ActionClass.STATE,
            description="Set a user preference. Schema-validated keys only.",
            input_schema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "enum": ["default_signature", "summary_style"],
                    },
                    "value": {"type": "string", "maxLength": 2000},
                },
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        )
    )

    reg.register(
        ToolSpec(
            name="browser.click",
            version="1",
            action_class=ActionClass.GATED_PRIMITIVE,
            description="Low-level click. Hidden unless primitives are explicitly enabled.",
            input_schema={
                "type": "object",
                "properties": {"ref": {"type": "string"}},
                "required": ["ref"],
                "additionalProperties": False,
            },
            hidden_by_default=True,
        )
    )

    return reg
