"""Harness scenario tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from openclaw.harness.runner import HarnessRunner
from openclaw.runtime.bootstrap import build_engine
from openclaw.runtime.modes import RuntimeMode

SCENARIO_DIR = (
    Path(__file__).parent.parent / "src" / "openclaw" / "harness" / "scenarios"
)


def test_summarize_unread_mail_scenario_passes_against_fake_provider():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        runner = HarnessRunner(engine)
        report = runner.run_scenario(SCENARIO_DIR / "summarize_unread_mail.yaml")
        assert report.passed, report.failures
        assert report.step_count == 2
        assert report.session_id.startswith("sess_")


def test_refuse_primitive_scenario_passes_when_primitives_disabled():
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(
            base_dir=Path(d),
            mode=RuntimeMode.HARNESS_FAKE,
            primitives_enabled=False,
        )
        runner = HarnessRunner(engine)
        report = runner.run_scenario(
            SCENARIO_DIR / "refuse_primitive_when_gated.yaml"
        )
        assert report.passed, report.failures


def test_scenario_session_id_is_stable_across_all_steps():
    """One session_id per scenario run, threaded into every step's envelope."""
    with tempfile.TemporaryDirectory() as d:
        engine = build_engine(base_dir=Path(d), mode=RuntimeMode.HARNESS_FAKE)
        runner = HarnessRunner(engine)
        report = runner.run_scenario(SCENARIO_DIR / "summarize_unread_mail.yaml")
        assert report.passed

        envelopes = [
            json.loads(line)
            for line in (Path(d) / "audit.log").read_text().splitlines()
            if line.strip()
        ]
        scenario_envs = [
            e for e in envelopes if e.get("scenario_id") == "summarize_unread_mail"
        ]
        # All envelopes for this scenario share the same session_id.
        session_ids = {e["session_id"] for e in scenario_envs}
        assert len(session_ids) == 1
        assert session_ids.pop() == report.session_id
