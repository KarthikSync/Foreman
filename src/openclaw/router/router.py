"""Provider Router. Reviewer ordering item #4.

Walks a provider chain. Records `provider_attempt` for the envelope.
Falls back on non-terminal failures; honors `terminal=True` for safety-relevant
errors that should not be retried with a different provider.
"""

from __future__ import annotations

from openclaw.providers.base import Provider
from openclaw.types.core import ProviderResult, ToolCall


class ProviderRouter:
    def __init__(self, providers: dict[str, Provider]) -> None:
        self._providers = providers

    @property
    def providers(self) -> dict[str, Provider]:
        return self._providers

    def invoke(
        self,
        tool_call: ToolCall,
        provider_chain: tuple[str, ...],
    ) -> tuple[str | None, int, ProviderResult]:
        """Walk the chain. Returns (provider_used, attempts, result)."""
        attempts = 0
        last_result: ProviderResult | None = None

        for provider_id in provider_chain:
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            if not provider.supports(tool_call.tool, tool_call.profile):
                continue
            attempts += 1
            result = provider.invoke(tool_call)
            if result.ok or result.terminal:
                return provider_id, attempts, result
            last_result = result

        if last_result is not None:
            return None, attempts, last_result

        return None, 0, ProviderResult(
            ok=False,
            error_code="provider_unavailable",
            error_message="No provider in chain supported this tool.",
        )
