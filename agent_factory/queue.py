from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonio import read_json, write_json


@dataclass(frozen=True)
class ClaimedJob:
    job: dict[str, Any]
    queue: dict[str, Any]


def claim_next_job(queue_file: Path, role: str, worker_id: str) -> ClaimedJob | None:
    queue = read_json(queue_file)
    for job in queue.get("jobs", []):
        if job.get("role") != role or job.get("status") != "queued":
            continue
        if any(not _dependency_passed(queue, dependency) for dependency in job.get("depends_on", [])):
            continue
        job["status"] = "running"
        job["lease_owner"] = worker_id
        job["attempt"] = int(job.get("attempt", 0)) + 1
        write_json(queue_file, queue)
        return ClaimedJob(job=job, queue=queue)
    return None


def complete_job(queue_file: Path, job_id: str) -> None:
    queue = read_json(queue_file)
    _update_job(queue, job_id, {"status": "passed", "lease_owner": None})
    write_json(queue_file, queue)


def fail_job(queue_file: Path, job_id: str, error: str) -> None:
    queue = read_json(queue_file)
    _update_job(queue, job_id, {"status": "failed", "lease_owner": None, "error": error})
    write_json(queue_file, queue)


def _dependency_passed(queue: dict[str, Any], job_id: str) -> bool:
    for job in queue.get("jobs", []):
        if job.get("id") == job_id:
            return job.get("status") == "passed"
    return False


def _update_job(queue: dict[str, Any], job_id: str, patch: dict[str, Any]) -> None:
    for job in queue.get("jobs", []):
        if job.get("id") == job_id:
            job.update(patch)
            return
    raise ValueError(f"job not found: {job_id}")
