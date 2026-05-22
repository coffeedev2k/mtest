from __future__ import annotations

import json
from pathlib import Path

from agent_factory.runtime import create_run
from agent_factory.worker import main as worker_main
from tests.conftest import write_fake_factory_config


def test_planner_worker_claims_job_and_writes_plan(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Test Feature\n", encoding="utf-8")
    write_fake_factory_config(config)
    run = create_run(feature, config, status="running")

    exit_code = worker_main(["--role", "planner", "--run", str(run.run_dir), "--repo", str(tmp_path), "--once"])

    assert exit_code == 0
    assert (run.run_dir / "plan.md").is_file()
    queue = json.loads(run.queue_file.read_text(encoding="utf-8"))
    assert queue["jobs"][0]["status"] == "passed"


def test_architect_worker_waits_for_dependency(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Test Feature\n", encoding="utf-8")
    write_fake_factory_config(config)
    run = create_run(feature, config, status="running")

    exit_code = worker_main(["--role", "architect", "--run", str(run.run_dir), "--repo", str(tmp_path), "--once"])

    assert exit_code == 0
    assert not (run.run_dir / "architecture.md").exists()
    queue = json.loads(run.queue_file.read_text(encoding="utf-8"))
    assert queue["jobs"][1]["status"] == "queued"
