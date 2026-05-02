"""Agent Harness scenario runner.

Runs YAML scenarios through the same OpenClawEngine that handles live MCP
traffic. v0.1 supports:

  - linear step lists (no branching yet)
  - allowed_tools / forbidden_tools enforcement
  - declarative success criteria
  - per-step expectations
  - one stable session_id per scenario run, threaded into every step's envelope

Out of scope for v0.1:
  - record / replay against captured traces
  - golden trace storage and diffing
  - HarnessModelDriver layer

Those land in the next milestone alongside the live BrowserProvider work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from openclaw.runtime.engine import OpenClawEngine
from openclaw.types.core import ToolCall


def _new_session_id() -> str:
    return f"sess_{uuid4().hex[:26].upper()}"


@dataclass
class ScenarioReport:
    scenario_id: str
    session_id: str
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    step_count: int = 0


class HarnessRunner:
    def __init__(self, engine: OpenClawEngine) -> None:
        self._engine = engine

    def run_scenario(self, scenario_path: Path) -> ScenarioReport:
        with scenario_path.open("r", encoding="utf-8") as f:
            scenario: dict[str, Any] = yaml.safe_load(f)

        scenario_id: str = scenario["id"]
        steps: list[dict[str, Any]] = scenario.get("steps", [])
        forbidden = set(scenario.get("forbidden_tools", []))
        allowed = scenario.get("allowed_tools")
        criteria = set(scenario.get("success_criteria", []))

        # One session_id for the whole scenario. Threading it into every
        # ToolCall lets audit/correlation/grouping queries work properly.
        session_id = _new_session_id()

        report = ScenarioReport(
            scenario_id=scenario_id,
            session_id=session_id,
            step_count=len(steps),
        )
        results = []

        for step in steps:
            step_name = step.get("name", step["tool"])
            tool = step["tool"]

            if tool in forbidden:
                report.passed = False
                report.failures.append(
                    f"step '{step_name}': forbidden tool used: {tool}"
                )
                continue
            if allowed is not None and tool not in allowed:
                report.passed = False
                report.failures.append(
                    f"step '{step_name}': tool {tool} not in allowed_tools"
                )
                continue

            call = ToolCall(
                tool=tool,
                inputs=step.get("inputs", {}),
                scenario_id=scenario_id,
                session_id=session_id,
            )
            result = self._engine.execute(call)
            results.append(result)

            expect = step.get("expect", {})
            if expect.get("ok") is True and not result.ok:
                report.passed = False
                report.failures.append(
                    f"step '{step_name}': expected ok, got error_code="
                    f"{result.error_code}: {result.error_message}"
                )
            if expect.get("ok") is False and result.ok:
                report.passed = False
                report.failures.append(
                    f"step '{step_name}': expected failure, got success"
                )
            if "min_messages" in expect:
                msgs = (result.data or {}).get("messages", [])
                if len(msgs) < expect["min_messages"]:
                    report.passed = False
                    report.failures.append(
                        f"step '{step_name}': expected >= {expect['min_messages']} "
                        f"messages, got {len(msgs)}"
                    )

        # Scenario-wide success criteria.
        if "all_outputs_carry_taint_tags" in criteria:
            for i, r in enumerate(results):
                if not r.ok:
                    continue
                data = r.data or {}
                # If the response includes external content, taint is required.
                if data.get("messages") or data.get("body") or data.get("subject"):
                    if not r.taint:
                        report.passed = False
                        report.failures.append(
                            f"result[{i}]: external content returned without taint tags"
                        )

        if "no_destructive_action" in criteria:
            envelopes = self._engine.audit.read_all()
            scenario_envelopes = [
                e for e in envelopes if e.get("session_id") == session_id
            ]
            for e in scenario_envelopes:
                if e.get("action_class") == "destructive":
                    report.passed = False
                    report.failures.append(
                        f"audit shows destructive action in scenario: {e.get('tool')}"
                    )

        return report
