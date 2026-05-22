from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_cli_dry_run_creates_factory_run(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    config = tmp_path / "factory.yaml"
    feature.write_text("# Helm Patch Syncer\n", encoding="utf-8")
    shutil.copy2("factory.yaml", config)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_factory",
            "run",
            str(feature),
            "--config",
            str(config),
            "--dry-run",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "created run:" in completed.stdout
    run_dir = tmp_path / "runs" / "001"
    assert (run_dir / "state.json").is_file()
    assert (run_dir / "queue.json").is_file()
    assert (run_dir / "locks.json").is_file()
    assert (run_dir / "logs" / "events.jsonl").is_file()

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "dry_run"
    assert state["worker_topology"]["planner"]["concurrency"] == 1
