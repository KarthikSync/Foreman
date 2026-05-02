"""Selector pack base class.

A selector pack covers one UI variant of one surface (e.g., Outlook Monarch).
Concrete subclasses set `name` and `supported_tools` as class attributes and
implement per-tool methods that the BrowserProvider dispatches to.
"""

from __future__ import annotations

from abc import ABC


class SelectorPack(ABC):
    name: str = ""
    supported_tools: frozenset[str] = frozenset()

    def supports(self, tool_name: str) -> bool:
        return tool_name in self.supported_tools
