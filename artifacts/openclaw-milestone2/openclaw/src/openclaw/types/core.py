"""Core types for OpenClaw runtime.

Reviewer ordering item #1: ToolCall, ToolResult, ToolExecutionEnvelope,
ActionClass, TaintTag, ProviderResult, ProfileContext.

All persisted objects carry profile_id from day one (spec §16.5).
External content carries TaintTag from the moment of extraction (spec §11.2).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _ulid_like() -> str:
    """A cheap ULID-shaped identifier; collision-resistant enough for v0.1."""
    return uuid4().hex[:26].upper()


class ActionClass(str, Enum):
    """Safety classification declared per tool. See spec §11.1."""

    READ = "read"
    STATE = "state"
    DESTRUCTIVE = "destructive"
    GATED_PRIMITIVE = "gated_primitive"


class TrustLevel(str, Enum):
    """Trust attribution for output content."""

    TRUSTED_SYSTEM = "trusted_system"
    UNTRUSTED_USER_CONTENT = "untrusted_user_content"
    UNTRUSTED_EXTERNAL = "untrusted_external"


class TaintTag(BaseModel):
    """Marks a field of a tool output as carrying untrusted content."""

    model_config = ConfigDict(frozen=True)

    field: str
    trust: TrustLevel
    source: str  # e.g. "outlook_email_body"


class ProfileContext(BaseModel):
    """Profile binding for a single tool invocation."""

    profile_id: str = "default"


class ToolCall(BaseModel):
    """Inbound call to the runtime."""

    tool: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    profile: ProfileContext = Field(default_factory=ProfileContext)
    session_id: str = Field(default_factory=lambda: f"sess_{_ulid_like()}")
    scenario_id: str | None = None
    tool_call_id: str = Field(default_factory=lambda: f"tc_{_ulid_like()}")


class ProviderResult(BaseModel):
    """Result of a single provider attempt.

    `terminal=True` instructs the router NOT to fall back to the next provider.
    Used for safety-relevant errors like needs_interactive_login or domain_blocked
    where retrying with a different provider is incorrect.
    """

    ok: bool
    data: dict[str, Any] | None = None
    taint: list[TaintTag] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    terminal: bool = False


class ToolResult(BaseModel):
    """Final result returned to the MCP client, after router + governor."""

    ok: bool
    data: dict[str, Any] | None = None
    taint: list[TaintTag] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class ToolExecutionEnvelope(BaseModel):
    """The single normalized record per tool invocation. See spec §5.

    Feeds audit, harness traces, debugging, provider reliability stats,
    and (when opted-in) telemetry.
    """

    model_config = ConfigDict(use_enum_values=True)

    tool_call_id: str
    session_id: str
    profile_id: str
    scenario_id: str | None
    tool: str
    tool_version: str
    provider: str | None
    provider_attempt: int
    action_class: ActionClass
    inputs_redacted: dict[str, Any]
    taint_inputs: list[TaintTag]
    taint_outputs: list[TaintTag]
    requires_approval: bool
    approval_id: str | None
    approval_token_used: str | None
    started_at: datetime
    duration_ms: int
    outcome: str  # "success" | "failure"
    error_code: str | None
    correlation_id: str

    def to_jsonl(self) -> str:
        return self.model_dump_json()
