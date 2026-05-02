"""Append-only JSONL audit trace. See spec §15.1.

One envelope per tool invocation, validated against the ToolExecutionEnvelope
schema before being written. The same envelope feeds harness reports and,
when opted-in, telemetry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openclaw.types.core import ToolExecutionEnvelope


class AuditTrace:
    def __init__(self, log_path: Path) -> None:
        self._path = log_path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, envelope: ToolExecutionEnvelope) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(envelope.to_jsonl() + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
