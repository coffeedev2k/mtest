from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import FactoryConfig, load_factory_config


@dataclass(frozen=True)
class DryRunResult:
    run_dir: Path
    state_file: Path
    queue_file: Path
    locks_file: Path
    events_file: Path


def create_dry_run(feature_path: Path, config_path: Path) -> DryRunResult:
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
        "status": "dry_run",
        "feature": str(run_dir / "input" / feature_path.name),
        "config": str(run_dir / "input" / config_path.name),
        "created_at": now,
        "runtime": config.runtime,
        "backend": config.backend,
        "worker_topology": _worker_topology(config),
    }
    queue = {
        "status": "dry_run",
        "jobs": [
            {
                "id": "job-001",
                "role": "planner",
                "status": "queued",
                "depends_on": [],
                "input_artifacts": [f"input/{feature_path.name}", f"input/{config_path.name}"],
                "expected_outputs": ["plan.md"],
                "lease_owner": None,
                "attempt": 0,
            }
        ],
    }
    locks = {
        "write_scopes": {},
        "leases": {},
    }

    state_file = run_dir / "state.json"
    queue_file = run_dir / "queue.json"
    locks_file = run_dir / "locks.json"
    events_file = run_dir / "logs" / "events.jsonl"

    _write_json(state_file, state)
    _write_json(queue_file, queue)
    _write_json(locks_file, locks)
    _append_event(events_file, "run_created", {"run_id": run_dir.name})
    _append_event(events_file, "dry_run_created", {"worker_topology": state["worker_topology"]})

    return DryRunResult(
        run_dir=run_dir,
        state_file=state_file,
        queue_file=queue_file,
        locks_file=locks_file,
        events_file=events_file,
    )


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
            "prompt": agent.prompt,
            "outputs": list(agent.outputs),
        }
        for agent in config.agents
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_event(path: Path, event_type: str, payload: dict[str, Any]) -> None:
    event = {
        "type": event_type,
        "time": _now(),
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
