"""OpenClaw CLI.

Two commands in v0.1:

  openclaw serve --stdio
      Start the MCP stdio server in SERVE_LOCAL mode.
      (Production providers only — fake_outlook is NOT routable here.)

  openclaw harness run <scenario> --provider {fake|live}
      Run a harness scenario against the same engine path.
        --provider fake -> RuntimeMode.HARNESS_FAKE  (deterministic, no browser)
        --provider live -> RuntimeMode.HARNESS_LIVE  (rejected in v0.1 skeleton)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from openclaw.harness.runner import HarnessRunner
from openclaw.runtime.bootstrap import build_engine
from openclaw.runtime.modes import RuntimeMode

DEFAULT_BASE = Path(
    os.environ.get("OPENCLAW_HOME", str(Path.home() / ".openclaw"))
)
DEFAULT_SCENARIO_DIR = Path(__file__).parent / "harness" / "scenarios"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openclaw")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE)

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Start the MCP server (SERVE_LOCAL mode)")
    p_serve.add_argument(
        "--stdio",
        action="store_true",
        help="Use stdio transport (the only transport in v0.1).",
    )

    p_harness = sub.add_parser("harness", help="Harness operations")
    h_sub = p_harness.add_subparsers(dest="harness_cmd", required=True)

    p_run = h_sub.add_parser("run", help="Run a scenario")
    p_run.add_argument("scenario", help="Scenario name (e.g. summarize_unread_mail)")
    p_run.add_argument(
        "--provider",
        default="fake",
        choices=["fake", "live"],
        help="fake -> HARNESS_FAKE, live -> HARNESS_LIVE (not in v0.1 skeleton).",
    )
    p_run.add_argument("--scenario-dir", type=Path, default=None)
    p_run.add_argument(
        "--enable-primitives",
        action="store_true",
        help="Surface gated primitives. Harness-only, never in MCP serve.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "serve":
        from openclaw.mcp_server.server import serve_stdio

        # SERVE_LOCAL: production chains only. fake_outlook is not in the chain.
        asyncio.run(serve_stdio(args.base_dir))
        return 0

    if args.cmd == "harness" and args.harness_cmd == "run":
        if args.provider == "live":
            print(
                "Live provider mode (HARNESS_LIVE) is not implemented in v0.1 skeleton. "
                "Use --provider fake.",
                file=sys.stderr,
            )
            return 2

        mode = RuntimeMode.HARNESS_FAKE  # the only mode supported in v0.1 harness CLI
        engine = build_engine(
            base_dir=args.base_dir,
            mode=mode,
            primitives_enabled=args.enable_primitives,
        )
        scenario_dir = args.scenario_dir or DEFAULT_SCENARIO_DIR
        scenario_path = scenario_dir / f"{args.scenario}.yaml"
        if not scenario_path.exists():
            print(f"Scenario not found: {scenario_path}", file=sys.stderr)
            return 2

        runner = HarnessRunner(engine)
        report = runner.run_scenario(scenario_path)

        verdict = "PASS" if report.passed else "FAIL"
        print(f"Scenario:   {report.scenario_id}")
        print(f"Mode:       {mode.value}")
        print(f"Session:    {report.session_id}")
        print(f"Steps:      {report.step_count}")
        print(f"Result:     {verdict}")
        for failure in report.failures:
            print(f"  - {failure}")
        return 0 if report.passed else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
