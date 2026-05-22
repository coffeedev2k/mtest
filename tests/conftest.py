from __future__ import annotations

from pathlib import Path


def write_fake_factory_config(path: Path) -> None:
    path.write_text(
        """
factory:
  name: test-agent-factory
  run_root: runs
  runtime: python_workers
  backend: fake_planner
  require_review: true
  require_tests: true
  max_fix_loops: 3

backend:
  fake_planner:
    command: fake-planner
    args: []

agents:
  planner:
    worker_module: agent_factory.worker
    prompt: agents/planner.md
    concurrency: 1
    outputs:
      - plan.md
  implementer:
    worker_module: agent_factory.worker
    prompt: agents/implementer.md
    concurrency: 2
    outputs:
      - implementation-report.md
""",
        encoding="utf-8",
    )
