from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import FactoryConfig, load_factory_config
from .events import append_event
from .jsonio import read_json, write_json

ROLE_SEQUENCE = ("planner", "architect", "task_generator")
TASK_EXECUTION_SEQUENCE = ("implementer", "reviewer", "tester")


@dataclass(frozen=True)
class DryRunResult:
    run_dir: Path
    state_file: Path
    queue_file: Path
    locks_file: Path
    events_file: Path


@dataclass(frozen=True)
class BuildResult:
    planning_run: DryRunResult
    execution_run: DryRunResult
    task_file: Path
    commit_sha: str | None


def create_dry_run(feature_path: Path, config_path: Path) -> DryRunResult:
    return create_run(feature_path, config_path, status="dry_run")


def create_run(feature_path: Path, config_path: Path, status: str = "running") -> DryRunResult:
    feature_path = feature_path.resolve()
    config_path = config_path.resolve()
    if not feature_path.is_file():
        raise FileNotFoundError(f"feature file not found: {feature_path}")
    if not config_path.is_file():
        raise FileNotFoundError(f"factory config not found: {config_path}")

    config = load_factory_config(config_path)
    repo_root = config_path.parent
    run_dir = _next_run_dir(repo_root / config.run_root)
    _create_run_layout(run_dir)

    shutil.copy2(feature_path, run_dir / "input" / feature_path.name)
    shutil.copy2(config_path, run_dir / "input" / config_path.name)

    now = _now()
    state = {
        "run_id": run_dir.name,
        "status": status,
        "feature": str(run_dir / "input" / feature_path.name),
        "config": str(run_dir / "input" / config_path.name),
        "created_at": now,
        "runtime": config.runtime,
        "backend": config.backend,
        "worker_topology": _worker_topology(config),
    }
    queue = {
        "status": status,
        "jobs": _initial_jobs(feature_path.name, config_path.name),
    }
    locks = {
        "write_scopes": {},
        "leases": {},
    }

    state_file = run_dir / "state.json"
    queue_file = run_dir / "queue.json"
    locks_file = run_dir / "locks.json"
    events_file = run_dir / "logs" / "events.jsonl"

    write_json(state_file, state)
    write_json(queue_file, queue)
    write_json(locks_file, locks)
    append_event(events_file, "run_created", {"run_id": run_dir.name, "status": status})
    if status == "dry_run":
        append_event(events_file, "dry_run_created", {"worker_topology": state["worker_topology"]})

    return DryRunResult(
        run_dir=run_dir,
        state_file=state_file,
        queue_file=queue_file,
        locks_file=locks_file,
        events_file=events_file,
    )


def run_only(feature_path: Path, config_path: Path, role: str) -> DryRunResult:
    roles = ROLE_SEQUENCE[: ROLE_SEQUENCE.index(role) + 1]
    return run_roles(feature_path, config_path, roles)


def run_roles(feature_path: Path, config_path: Path, roles: tuple[str, ...]) -> DryRunResult:
    result = create_run(feature_path, config_path, status="running")
    repo_root = config_path.resolve().parent
    config = load_factory_config(result.run_dir / "input" / "factory.yaml")
    _progress(result, f"created run {result.run_dir.name}")
    for role in roles:
        _run_worker_process(result, repo_root, config, role)

    queue = read_json(result.queue_file)
    state = read_json(result.state_file)
    last_role = roles[-1]
    state["status"] = _gate_for_role(last_role)
    state["last_completed_role"] = last_role
    state["queue_status"] = _job_status(queue, last_role)
    write_json(result.state_file, state)
    append_event(result.events_file, "run_paused_at_gate", {"gate": state["status"]})
    _progress(result, f"paused at {state['status']}")
    return result


def run_task(task_path: Path, config_path: Path) -> DryRunResult:
    task_path = task_path.resolve()
    config_path = config_path.resolve()
    if not task_path.is_file():
        raise FileNotFoundError(f"task file not found: {task_path}")
    if not config_path.is_file():
        raise FileNotFoundError(f"factory config not found: {config_path}")

    config = load_factory_config(config_path)
    repo_root = config_path.parent
    run_dir = _next_run_dir(repo_root / config.run_root)
    _create_run_layout(run_dir)
    shutil.copy2(task_path, run_dir / "input" / "task.md")
    shutil.copy2(config_path, run_dir / "input" / config_path.name)

    state = {
        "run_id": run_dir.name,
        "status": "running",
        "task": str(run_dir / "input" / "task.md"),
        "config": str(run_dir / "input" / config_path.name),
        "created_at": _now(),
        "runtime": config.runtime,
        "backend": config.backend,
        "worker_topology": _worker_topology(config),
    }
    queue = {
        "status": "running",
        "jobs": _task_execution_jobs(),
    }
    locks = {
        "write_scopes": {},
        "leases": {},
    }

    result = DryRunResult(
        run_dir=run_dir,
        state_file=run_dir / "state.json",
        queue_file=run_dir / "queue.json",
        locks_file=run_dir / "locks.json",
        events_file=run_dir / "logs" / "events.jsonl",
    )
    write_json(result.state_file, state)
    write_json(result.queue_file, queue)
    write_json(result.locks_file, locks)
    append_event(result.events_file, "run_created", {"run_id": run_dir.name, "status": "running"})
    _progress(result, f"created task execution run {run_dir.name}")
    for role in TASK_EXECUTION_SEQUENCE:
        _run_worker_process(result, repo_root, config, role)

    queue = read_json(result.queue_file)
    state = read_json(result.state_file)
    state["status"] = "task_execution_gate"
    state["last_completed_role"] = "tester"
    state["queue_status"] = _job_status(queue, "tester")
    write_json(result.state_file, state)
    append_event(result.events_file, "run_paused_at_gate", {"gate": state["status"]})
    _progress(result, "paused at task_execution_gate")
    return result


def build_feature(feature_path: Path, config_path: Path, commit: bool = True) -> BuildResult:
    _print_global_progress("starting build")
    planning = run_only(feature_path, config_path, "task_generator")
    task_file = planning.run_dir / "tasks" / "001-chartpatch-plan.md"
    _print_global_progress(f"generated task {task_file}")
    execution = run_task(task_file, config_path)
    commit_sha = None
    if commit:
        commit_sha = _commit_gate(config_path.resolve().parent, task_file)
        _print_global_progress(f"created gate commit {commit_sha}")
    _print_global_progress("build complete")
    return BuildResult(
        planning_run=planning,
        execution_run=execution,
        task_file=task_file,
        commit_sha=commit_sha,
    )


def _run_worker_process(result: DryRunResult, repo_root: Path, config: FactoryConfig, role: str) -> None:
    agent = _agent_config(config, role)
    command = [
        sys.executable,
        "-m",
        "agent_factory.worker",
        "--role",
        role,
        "--run",
        str(result.run_dir),
        "--repo",
        str(repo_root),
        "--once",
    ]
    _progress(result, f"starting {role} worker with timeout {agent.timeout_seconds}s")
    append_event(result.events_file, "worker_process_starting", {"role": role, "command": command})
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=agent.timeout_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        _write_worker_logs(result, role, stdout, stderr)
        _mark_blocked(
            result,
            role,
            f"{role} worker exceeded timeout of {agent.timeout_seconds}s",
        )
        return

    _write_worker_logs(result, role, stdout, stderr)
    append_event(
        result.events_file,
        "worker_process_finished",
        {"role": role, "returncode": process.returncode},
    )
    if process.returncode != 0:
        state = read_json(result.state_file)
        state["status"] = "failed"
        state["failed_role"] = role
        write_json(result.state_file, state)
        _progress(result, f"{role} worker failed with exit code {process.returncode}")
        raise RuntimeError(f"{role} worker failed with exit code {process.returncode}")
    _progress(result, f"{role} worker finished")


def _next_run_dir(run_root: Path) -> Path:
    run_root.mkdir(parents=True, exist_ok=True)
    existing = [path.name for path in run_root.iterdir() if path.is_dir() and path.name.isdigit()]
    next_id = max([int(name) for name in existing], default=0) + 1
    return run_root / f"{next_id:03d}"


def _create_run_layout(run_dir: Path) -> None:
    for relative in ["input", "tasks", "agents", "logs"]:
        (run_dir / relative).mkdir(parents=True, exist_ok=False)


def _worker_topology(config: FactoryConfig) -> dict[str, Any]:
    return {
        agent.name: {
            "worker_module": agent.worker_module,
            "concurrency": agent.concurrency,
            "timeout_seconds": agent.timeout_seconds,
            "sandbox": agent.sandbox,
            "prompt": agent.prompt,
            "outputs": list(agent.outputs),
        }
        for agent in config.agents
    }


def _initial_jobs(feature_name: str, config_name: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "job-001",
            "role": "planner",
            "status": "queued",
            "depends_on": [],
            "input_artifacts": [f"input/{feature_name}", f"input/{config_name}"],
            "expected_outputs": ["plan.md"],
            "lease_owner": None,
            "attempt": 0,
        },
        {
            "id": "job-002",
            "role": "architect",
            "status": "queued",
            "depends_on": ["job-001"],
            "input_artifacts": [f"input/{feature_name}", "plan.md", f"input/{config_name}"],
            "expected_outputs": ["architecture.md"],
            "lease_owner": None,
            "attempt": 0,
        },
        {
            "id": "job-003",
            "role": "task_generator",
            "status": "queued",
            "depends_on": ["job-002"],
            "input_artifacts": [
                f"input/{feature_name}",
                "plan.md",
                "architecture.md",
                f"input/{config_name}",
            ],
            "expected_outputs": ["tasks/001-chartpatch-plan.md"],
            "lease_owner": None,
            "attempt": 0,
        },
    ]


def _task_execution_jobs() -> list[dict[str, Any]]:
    return [
        {
            "id": "job-004",
            "role": "implementer",
            "status": "queued",
            "depends_on": [],
            "input_artifacts": ["input/task.md", "input/factory.yaml"],
            "expected_outputs": ["implementation-report.md"],
            "lease_owner": None,
            "attempt": 0,
        },
        {
            "id": "job-005",
            "role": "reviewer",
            "status": "queued",
            "depends_on": ["job-004"],
            "input_artifacts": ["input/task.md", "implementation-report.md", "input/factory.yaml"],
            "expected_outputs": ["review-report.md"],
            "lease_owner": None,
            "attempt": 0,
        },
        {
            "id": "job-006",
            "role": "tester",
            "status": "queued",
            "depends_on": ["job-005"],
            "input_artifacts": [
                "input/task.md",
                "implementation-report.md",
                "review-report.md",
                "input/factory.yaml",
            ],
            "expected_outputs": ["test-report.md"],
            "lease_owner": None,
            "attempt": 0,
        },
    ]


def _gate_for_role(role: str) -> str:
    if role == "planner":
        return "planning_gate"
    if role == "architect":
        return "architecture_gate"
    if role == "task_generator":
        return "task_generation_gate"
    return "running"


def _job_status(queue: dict[str, Any], role: str) -> str:
    for job in queue.get("jobs", []):
        if job.get("role") == role:
            return str(job.get("status"))
    return "unknown"


def _agent_config(config: FactoryConfig, role: str):
    for agent in config.agents:
        if agent.name == role:
            return agent
    raise ValueError(f"agent config not found: {role}")


def _write_worker_logs(result: DryRunResult, role: str, stdout: str, stderr: str) -> None:
    (result.run_dir / "logs" / f"{role}.worker.stdout.log").write_text(stdout, encoding="utf-8")
    (result.run_dir / "logs" / f"{role}.worker.stderr.log").write_text(stderr, encoding="utf-8")


def _mark_blocked(result: DryRunResult, role: str, reason: str) -> None:
    state = read_json(result.state_file)
    state["status"] = "blocked"
    state["blocked_role"] = role
    state["blocked_reason"] = reason
    write_json(result.state_file, state)
    append_event(result.events_file, "worker_process_timeout", {"role": role, "reason": reason})
    append_event(result.events_file, "human_intervention_required", {"role": role, "reason": reason})
    _progress(result, f"blocked: {reason}")
    raise RuntimeError(reason)


def _progress(result: DryRunResult, message: str) -> None:
    append_event(result.events_file, "progress", {"message": message})
    print(f"[agent-factory] {message}", flush=True)


def _print_global_progress(message: str) -> None:
    print(f"[agent-factory] {message}", flush=True)


def _commit_gate(repo_root: Path, task_file: Path) -> str | None:
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )
    if not status.stdout.strip():
        return None
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    title = _task_title(task_file)
    subprocess.run(["git", "commit", "-m", title], cwd=repo_root, check=True)
    rev = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return rev.stdout.strip()


def _task_title(task_file: Path) -> str:
    for line in task_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Agent factory build gate"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
