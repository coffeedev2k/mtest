from __future__ import annotations

import json
from pathlib import Path

from agent_factory.queue import claim_next_job, complete_job


def test_claim_next_job_marks_job_running(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(
        json.dumps(
            {
                "status": "running",
                "jobs": [
                    {
                        "id": "job-001",
                        "role": "planner",
                        "status": "queued",
                        "depends_on": [],
                        "lease_owner": None,
                        "attempt": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    claimed = claim_next_job(queue_file, "planner", "worker-1")

    assert claimed is not None
    queue = json.loads(queue_file.read_text(encoding="utf-8"))
    assert queue["jobs"][0]["status"] == "running"
    assert queue["jobs"][0]["lease_owner"] == "worker-1"
    assert queue["jobs"][0]["attempt"] == 1


def test_claim_next_job_respects_dependencies(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.json"
    queue_file.write_text(
        json.dumps(
            {
                "status": "running",
                "jobs": [
                    {"id": "job-001", "role": "planner", "status": "running"},
                    {
                        "id": "job-002",
                        "role": "architect",
                        "status": "queued",
                        "depends_on": ["job-001"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert claim_next_job(queue_file, "architect", "worker-1") is None
    complete_job(queue_file, "job-001")
    assert claim_next_job(queue_file, "architect", "worker-1") is not None
