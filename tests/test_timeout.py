from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_factory.runtime import run_only


def test_run_only_blocks_when_worker_times_out(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Slow Feature\n", encoding="utf-8")
    config.write_text(
        """
factory:
  name: slow-agent-factory
  run_root: runs
  runtime: python_workers
  backend: fake_slow
  require_review: true
  require_tests: true
  max_fix_loops: 3

backend:
  fake_slow:
    command: fake-slow
    args: []

agents:
  planner:
    worker_module: agent_factory.worker
    prompt: agents/planner.md
    concurrency: 1
    timeout_seconds: 1
    outputs:
      - plan.md
  architect:
    worker_module: agent_factory.worker
    prompt: agents/architect.md
    concurrency: 1
    timeout_seconds: 1
    outputs:
      - architecture.md
  task_generator:
    worker_module: agent_factory.worker
    prompt: agents/task-generator.md
    concurrency: 1
    timeout_seconds: 1
    outputs:
      - tasks/
""",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="planner worker exceeded timeout of 1s"):
        run_only(feature, config, "planner")

    state = json.loads((tmp_path / "runs" / "001" / "state.json").read_text(encoding="utf-8"))
    events = (tmp_path / "runs" / "001" / "logs" / "events.jsonl").read_text(encoding="utf-8")
    assert state["status"] == "blocked"
    assert state["blocked_role"] == "planner"
    assert "human_intervention_required" in events
