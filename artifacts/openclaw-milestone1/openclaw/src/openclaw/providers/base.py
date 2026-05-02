"""Provider base interface. See spec §6 and §8.3."""

from __future__ import annotations

from abc import ABC, abstractmethod

from openclaw.types.core import ProfileContext, ProviderResult, ToolCall


class Provider(ABC):
    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @abstractmethod
    def supports(self, tool_name: str, profile: ProfileContext) -> bool:
        """Whether this provider can handle the given tool for the given profile."""

    @abstractmethod
    def invoke(self, call: ToolCall) -> ProviderResult: ...

    def close(self) -> None:
        """Tear down resources held by this provider.

        Default is a no-op; providers that hold a browser context, database
        cursor, or filesystem lock override this. Called by Engine.close()
        at process shutdown.
        """
        return None
