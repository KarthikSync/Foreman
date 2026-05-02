"""Closed error code enum. See spec §15.2."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    NEEDS_INTERACTIVE_LOGIN = "needs_interactive_login"
    ELEMENT_NOT_FOUND = "element_not_found"
    UI_VARIANT_UNSUPPORTED = "ui_variant_unsupported"
    TIMEOUT = "timeout"
    DOMAIN_BLOCKED = "domain_blocked"
    RATE_LIMITED = "rate_limited"
    NOT_CONFIRMED = "not_confirmed"
    APPROVAL_EXPIRED = "approval_expired"
    APPROVAL_REPLAYED = "approval_replayed"
    APPROVAL_ACTION_MISMATCH = "approval_action_mismatch"
    TAINT_VIOLATION = "taint_violation"
    SESSION_LOCKED = "session_locked"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NO_GROUNDED_ANSWER = "no_grounded_answer"
    INVALID_INPUT = "invalid_input"
    TOOL_NOT_FOUND = "tool_not_found"
    INTERNAL = "internal"
