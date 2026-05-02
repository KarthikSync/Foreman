"""MemoryProvider — exposes typed preference operations against the SQLite store."""

from __future__ import annotations

from openclaw.memory.store import MemoryStore
from openclaw.providers.base import Provider
from openclaw.types.core import ProfileContext, ProviderResult, ToolCall


_SUPPORTED_TOOLS = frozenset({"memory.preferences.get", "memory.preferences.set"})


class MemoryProvider(Provider):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def provider_id(self) -> str:
        return "memory"

    def supports(self, tool_name: str, profile: ProfileContext) -> bool:
        return tool_name in _SUPPORTED_TOOLS

    def invoke(self, call: ToolCall) -> ProviderResult:
        if call.tool == "memory.preferences.get":
            value = self._store.get_preference(
                call.profile.profile_id,
                call.inputs["key"],
            )
            return ProviderResult(ok=True, data={"value": value})

        if call.tool == "memory.preferences.set":
            try:
                self._store.set_preference(
                    call.profile.profile_id,
                    call.inputs["key"],
                    call.inputs["value"],
                )
            except ValueError as exc:
                return ProviderResult(
                    ok=False,
                    error_code="invalid_input",
                    error_message=str(exc),
                    terminal=True,
                )
            return ProviderResult(ok=True, data={"ok": True})

        return ProviderResult(
            ok=False,
            error_code="provider_unavailable",
            error_message=f"MemoryProvider does not support {call.tool}",
        )
