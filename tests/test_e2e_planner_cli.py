from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.conftest import write_factory_config, write_fake_factory_config


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


def test_cli_execute_task_runs_fix_loop_after_review_failure(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    config = tmp_path / "factory.yaml"
    task.write_text("# Task 001\n\nImplement something small.\n", encoding="utf-8")
    write_factory_config(config, backend="fake_review_fail_once")

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

    assert "reviewer failed; starting fix loop 1/3" in completed.stdout
    run_dir = tmp_path / "runs" / "001"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    queue = json.loads((run_dir / "queue.json").read_text(encoding="utf-8"))
    events = (run_dir / "logs" / "events.jsonl").read_text(encoding="utf-8")
    assert state["status"] == "task_execution_gate"
    assert "fix_loop_started" in events
    assert any(job.get("fix_for") == "reviewer" and job["status"] == "passed" for job in queue["jobs"])
    assert len([job for job in queue["jobs"] if job["role"] == "reviewer"]) == 2


def test_cli_execute_task_blocks_when_fix_loop_limit_is_exceeded(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    config = tmp_path / "factory.yaml"
    task.write_text("# Task 001\n\nImplement something small.\n", encoding="utf-8")
    write_factory_config(config, backend="fake_review_fail_once", max_fix_loops=0)

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
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    run_dir = tmp_path / "runs" / "001"
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    events = (run_dir / "logs" / "events.jsonl").read_text(encoding="utf-8")
    assert state["status"] == "blocked"
    assert state["blocked_role"] == "reviewer"
    assert "reviewer failed after 0 fix loop(s)" in state["blocked_reason"]
    assert "human_intervention_required" in events


def test_cli_build_runs_planning_and_execution_chains(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Helm Patch Syncer\n", encoding="utf-8")
    write_fake_factory_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_factory",
            "build",
            str(feature),
            "--config",
            str(config),
            "--no-commit",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "[agent-factory] starting build" in completed.stdout
    assert "planning run:" in completed.stdout
    assert "execution run:" in completed.stdout
    assert "commit: skipped" in completed.stdout
    assert "task cycle: 1" in completed.stdout
    planning_run = tmp_path / "runs" / "001"
    execution_run = tmp_path / "runs" / "002"
    memory = tmp_path / "build-memory.md"
    assert (planning_run / "tasks" / "001-chartpatch-plan.md").is_file()
    assert (planning_run / "input" / "build-memory.md").is_file()
    assert (execution_run / "implementation-report.md").is_file()
    assert (execution_run / "review-report.md").is_file()
    assert (execution_run / "test-report.md").is_file()
    assert "Task cycle 1" in memory.read_text(encoding="utf-8")


def test_cli_build_max_tasks_runs_multiple_cycles(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Helm Patch Syncer\n", encoding="utf-8")
    write_fake_factory_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_factory",
            "build",
            str(feature),
            "--config",
            str(config),
            "--max-tasks",
            "2",
            "--no-commit",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "task cycle: 1" in completed.stdout
    assert "task cycle: 2" in completed.stdout
    assert completed.stdout.count("commit: skipped") == 2
    memory = (tmp_path / "build-memory.md").read_text(encoding="utf-8")
    assert (tmp_path / "runs" / "001" / "tasks" / "001-chartpatch-plan.md").is_file()
    assert (tmp_path / "runs" / "002" / "test-report.md").is_file()
    assert (tmp_path / "runs" / "003" / "tasks" / "001-chartpatch-plan.md").is_file()
    assert (tmp_path / "runs" / "003" / "input" / "build-memory.md").is_file()
    assert (tmp_path / "runs" / "004" / "test-report.md").is_file()
    assert "Task cycle 1" in memory
    assert "Task cycle 2" in memory
    assert "execution_run:" in memory
