from __future__ import annotations

import json
from pathlib import Path

from agent_factory.status import render_status


def test_render_status_shows_jobs_and_blocked_reason(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "001"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "001",
                "status": "blocked",
                "backend": "fake_slow",
                "blocked_reason": "planner worker exceeded timeout of 1s",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "queue.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {"id": "job-001", "role": "planner", "status": "running", "lease_owner": "planner-host"}
                ]
            }
        ),
        encoding="utf-8",
    )

    output = render_status(run_dir)

    assert "status: blocked" in output
    assert "job-001: planner -> running (planner-host)" in output
    assert "blocked_reason: planner worker exceeded timeout of 1s" in output
