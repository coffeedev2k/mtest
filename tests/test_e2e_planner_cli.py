from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.conftest import write_fake_factory_config


def test_cli_only_planner_runs_worker_and_stops_at_gate(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Helm Patch Syncer\n", encoding="utf-8")
    write_fake_factory_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_factory",
            "run",
            str(feature),
            "--config",
            str(config),
            "--only",
            "planner",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "gate: planner" in completed.stdout
    run_dir = tmp_path / "runs" / "001"
    assert (run_dir / "plan.md").is_file()
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    queue = json.loads((run_dir / "queue.json").read_text(encoding="utf-8"))
    assert state["status"] == "planning_gate"
    assert queue["jobs"][0]["status"] == "passed"
    assert queue["jobs"][1]["status"] == "queued"


def test_cli_only_task_generator_runs_chain_and_stops_at_gate(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Helm Patch Syncer\n", encoding="utf-8")
    write_fake_factory_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_factory",
            "run",
            str(feature),
            "--config",
            str(config),
            "--only",
            "task_generator",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "gate: task_generator" in completed.stdout
    run_dir = tmp_path / "runs" / "001"
    assert (run_dir / "plan.md").is_file()
    assert (run_dir / "architecture.md").is_file()
    assert (run_dir / "tasks" / "001-chartpatch-plan.md").is_file()
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    queue = json.loads((run_dir / "queue.json").read_text(encoding="utf-8"))
    assert state["status"] == "task_generation_gate"
    assert [job["status"] for job in queue["jobs"]] == ["passed", "passed", "passed"]


def test_cli_execute_task_runs_implementation_chain(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    config = tmp_path / "factory.yaml"
    task.write_text("# Task 001\n\nImplement something small.\n", encoding="utf-8")
    write_fake_factory_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_factory",
            "execute-task",
            str(task),
            "--config",
            str(config),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "gate: task_execution" in completed.stdout
    run_dir = tmp_path / "runs" / "001"
    assert (run_dir / "implementation-report.md").is_file()
    assert (run_dir / "review-report.md").is_file()
    assert (run_dir / "test-report.md").is_file()
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    queue = json.loads((run_dir / "queue.json").read_text(encoding="utf-8"))
    assert state["status"] == "task_execution_gate"
    assert [job["status"] for job in queue["jobs"]] == ["passed", "passed", "passed"]
