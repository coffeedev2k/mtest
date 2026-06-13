from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
from pathlib import Path
from typing import Any

from .jsonio import read_json, write_json


@dataclass(frozen=True)
class ClaimedJob:
    job: dict[str, Any]
    queue: dict[str, Any]


def claim_next_job(
    queue_file: Path,
    role: str,
    worker_id: str,
    locks_file: Path | None = None,
) -> ClaimedJob | None:
    with _queue_lock(queue_file):
        queue = read_json(queue_file)
        locks = read_json(locks_file) if locks_file is not None else None
        for job in queue.get("jobs", []):
            if job.get("role") != role or job.get("status") != "queued":
                continue
            if any(
                not _dependency_passed(queue, dependency)
                for dependency in job.get("depends_on", [])
            ):
                continue
            if locks is not None and _write_scope_conflicts(
                locks, job.get("write_scope", [])
            ):
                continue
            job["status"] = "running"
            job["lease_owner"] = worker_id
            job["attempt"] = int(job.get("attempt", 0)) + 1
            write_json(queue_file, queue)
            if locks_file is not None and locks is not None:
                _claim_write_scope(locks, job)
                write_json(locks_file, locks)
            return ClaimedJob(job=job, queue=queue)
        return None


def complete_job(queue_file: Path, job_id: str, locks_file: Path | None = None) -> None:
    with _queue_lock(queue_file):
        queue = read_json(queue_file)
        _update_job(queue, job_id, {"status": "passed", "lease_owner": None})
        write_json(queue_file, queue)
        if locks_file is not None:
            _release_write_scope(locks_file, job_id)


def fail_job(queue_file: Path, job_id: str, error: str, locks_file: Path | None = None) -> None:
    with _queue_lock(queue_file):
        queue = read_json(queue_file)
        _update_job(queue, job_id, {"status": "failed", "lease_owner": None, "error": error})
        write_json(queue_file, queue)
        if locks_file is not None:
            _release_write_scope(locks_file, job_id)


@contextmanager
def _queue_lock(queue_file: Path):
    lock_file = queue_file.with_name(f".{queue_file.name}.lock")
    with lock_file.open("a+", encoding="utf-8") as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)


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


def _write_scope_conflicts(locks: dict[str, Any], write_scope: list[str]) -> bool:
    locked_scopes = locks.get("write_scopes", {})
    return any(scope in locked_scopes for scope in write_scope)


def _claim_write_scope(locks: dict[str, Any], job: dict[str, Any]) -> None:
    write_scope = list(job.get("write_scope", []))
    if not write_scope:
        return
    locks.setdefault("leases", {})[job["id"]] = write_scope
    locked_scopes = locks.setdefault("write_scopes", {})
    for scope in write_scope:
        locked_scopes[scope] = job["id"]


def _release_write_scope(locks_file: Path, job_id: str) -> None:
    locks = read_json(locks_file)
    scopes = locks.get("leases", {}).pop(job_id, [])
    for scope in scopes:
        if locks.get("write_scopes", {}).get(scope) == job_id:
            del locks["write_scopes"][scope]
    write_json(locks_file, locks)
