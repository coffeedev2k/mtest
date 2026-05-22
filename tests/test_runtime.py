from __future__ import annotations

import json
import shutil
from pathlib import Path

from agent_factory.runtime import create_dry_run


def test_create_dry_run_writes_core_artifacts(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Test Feature\n", encoding="utf-8")
    shutil.copy2("factory.yaml", config)

    result = create_dry_run(feature, config)

    assert result.run_dir.name == "001"
    assert result.state_file.is_file()
    assert result.queue_file.is_file()
    assert result.locks_file.is_file()
    assert result.events_file.is_file()

    state = json.loads(result.state_file.read_text(encoding="utf-8"))
    queue = json.loads(result.queue_file.read_text(encoding="utf-8"))

    assert state["status"] == "dry_run"
    assert state["worker_topology"]["implementer"]["concurrency"] == 2
    assert queue["jobs"][0]["role"] == "planner"
    assert queue["jobs"][0]["status"] == "queued"
    assert [job["role"] for job in queue["jobs"]] == ["planner", "architect", "task_generator"]
    assert queue["jobs"][1]["depends_on"] == ["job-001"]
    assert queue["jobs"][2]["depends_on"] == ["job-002"]


def test_create_dry_run_increments_run_id(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Test Feature\n", encoding="utf-8")
    shutil.copy2("factory.yaml", config)

    first = create_dry_run(feature, config)
    second = create_dry_run(feature, config)

    assert first.run_dir.name == "001"
    assert second.run_dir.name == "002"
