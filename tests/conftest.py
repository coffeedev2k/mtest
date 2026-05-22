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
    timeout_seconds: 30
    sandbox: read-only
    outputs:
      - plan.md
  implementer:
    worker_module: agent_factory.worker
    prompt: agents/implementer.md
    concurrency: 2
    timeout_seconds: 30
    sandbox: danger-full-access
    outputs:
      - implementation-report.md
  architect:
    worker_module: agent_factory.worker
    prompt: agents/architect.md
    concurrency: 1
    timeout_seconds: 30
    sandbox: read-only
    outputs:
      - architecture.md
  task_generator:
    worker_module: agent_factory.worker
    prompt: agents/task-generator.md
    concurrency: 1
    timeout_seconds: 30
    sandbox: read-only
    outputs:
      - tasks/
  reviewer:
    worker_module: agent_factory.worker
    prompt: agents/reviewer.md
    concurrency: 1
    timeout_seconds: 30
    sandbox: danger-full-access
    outputs:
      - review-report.md
  tester:
    worker_module: agent_factory.worker
    prompt: agents/tester.md
    concurrency: 1
    timeout_seconds: 30
    sandbox: danger-full-access
    outputs:
      - test-report.md
""",
        encoding="utf-8",
    )
