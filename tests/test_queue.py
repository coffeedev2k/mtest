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


def test_claim_next_job_respects_write_scope_locks(tmp_path: Path) -> None:
    queue_file = tmp_path / "queue.json"
    locks_file = tmp_path / "locks.json"
    queue_file.write_text(
        json.dumps(
            {
                "status": "running",
                "jobs": [
                    {
                        "id": "job-001",
                        "role": "implementer",
                        "status": "queued",
                        "depends_on": [],
                        "write_scope": ["src/a.py"],
                        "lease_owner": None,
                        "attempt": 0,
                    },
                    {
                        "id": "job-002",
                        "role": "implementer",
                        "status": "queued",
                        "depends_on": [],
                        "write_scope": ["src/a.py"],
                        "lease_owner": None,
                        "attempt": 0,
                    },
                    {
                        "id": "job-003",
                        "role": "implementer",
                        "status": "queued",
                        "depends_on": [],
                        "write_scope": ["src/b.py"],
                        "lease_owner": None,
                        "attempt": 0,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    locks_file.write_text(json.dumps({"write_scopes": {}, "leases": {}}), encoding="utf-8")

    first = claim_next_job(queue_file, "implementer", "worker-1", locks_file=locks_file)
    second = claim_next_job(queue_file, "implementer", "worker-2", locks_file=locks_file)

    assert first is not None
    assert first.job["id"] == "job-001"
    assert second is not None
    assert second.job["id"] == "job-003"
    locks = json.loads(locks_file.read_text(encoding="utf-8"))
    assert locks["write_scopes"] == {"src/a.py": "job-001", "src/b.py": "job-003"}

    complete_job(queue_file, "job-001", locks_file=locks_file)
    third = claim_next_job(queue_file, "implementer", "worker-3", locks_file=locks_file)

    assert third is not None
    assert third.job["id"] == "job-002"
