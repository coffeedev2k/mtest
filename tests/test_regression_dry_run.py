from __future__ import annotations

import json
import shutil
from pathlib import Path

from agent_factory.runtime import create_dry_run


def test_dry_run_state_shape_is_stable(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Helm Patch Syncer\n", encoding="utf-8")
    shutil.copy2("factory.yaml", config)

    result = create_dry_run(feature, config)
    state = json.loads(result.state_file.read_text(encoding="utf-8"))

    assert sorted(state) == [
        "backend",
        "config",
        "created_at",
        "feature",
        "run_id",
        "runtime",
        "status",
        "worker_topology",
    ]
    assert sorted(state["worker_topology"]) == [
        "architect",
        "implementer",
        "planner",
        "reviewer",
        "task_generator",
        "tester",
    ]


def test_dry_run_queue_shape_is_stable(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Helm Patch Syncer\n", encoding="utf-8")
    shutil.copy2("factory.yaml", config)

    result = create_dry_run(feature, config)
    queue = json.loads(result.queue_file.read_text(encoding="utf-8"))

    assert queue == {
        "jobs": [
            {
                "attempt": 0,
                "depends_on": [],
                "expected_outputs": ["plan.md"],
                "id": "job-001",
                "input_artifacts": ["input/feature.md", "input/factory.yaml"],
                "lease_owner": None,
                "role": "planner",
                "status": "queued",
            },
            {
                "attempt": 0,
                "depends_on": ["job-001"],
                "expected_outputs": ["architecture.md"],
                "id": "job-002",
                "input_artifacts": ["input/feature.md", "plan.md", "input/factory.yaml"],
                "lease_owner": None,
                "role": "architect",
                "status": "queued",
            },
            {
                "attempt": 0,
                "depends_on": ["job-002"],
                "expected_outputs": ["tasks/001-chartpatch-plan.md"],
                "id": "job-003",
                "input_artifacts": [
                    "input/feature.md",
                    "plan.md",
                    "architecture.md",
                    "input/factory.yaml",
                ],
                "lease_owner": None,
                "role": "task_generator",
                "status": "queued",
            }
        ],
        "status": "dry_run",
    }
