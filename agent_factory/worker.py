from __future__ import annotations

import argparse
import socket
from pathlib import Path

from .backend import run_backend
from .config import load_factory_config
from .events import append_event
from .queue import claim_next_job, complete_job, fail_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-factory-worker")
    parser.add_argument("--role", required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--once", action="store_true", help="Process at most one job")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo.resolve()
    run_dir = args.run.resolve()
    config = load_factory_config(run_dir / "input" / "factory.yaml")
    queue_file = run_dir / "queue.json"
    locks_file = run_dir / "locks.json"
    events_file = run_dir / "logs" / "events.jsonl"
    worker_id = f"{args.role}-{socket.gethostname()}"

    append_event(events_file, "worker_started", {"role": args.role, "worker_id": worker_id})
    claimed = claim_next_job(queue_file, args.role, worker_id, locks_file=locks_file)
    if claimed is None:
        append_event(events_file, "worker_idle", {"role": args.role, "worker_id": worker_id})
        return 0

    job = claimed.job
    append_event(events_file, "job_claimed", {"job_id": job["id"], "role": args.role})
    result = run_backend(config, repo_root, run_dir, args.role, job)
    (run_dir / "agents" / f"{args.role}.{job['id']}.stdout.log").write_text(result.stdout, encoding="utf-8")
    (run_dir / "agents" / f"{args.role}.{job['id']}.stderr.log").write_text(result.stderr, encoding="utf-8")
    for relative_path, content in result.outputs.items():
        output_path = run_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    missing_outputs = [output for output in job["expected_outputs"] if not (run_dir / output).exists()]
    if result.returncode != 0:
        error = f"backend exited with {result.returncode}"
        fail_job(queue_file, job["id"], error, locks_file=locks_file)
        append_event(events_file, "job_failed", {"job_id": job["id"], "error": error})
        return result.returncode
    if missing_outputs:
        error = f"missing outputs: {', '.join(missing_outputs)}"
        fail_job(queue_file, job["id"], error, locks_file=locks_file)
        append_event(events_file, "job_failed", {"job_id": job["id"], "error": error})
        return 1

    complete_job(queue_file, job["id"], locks_file=locks_file)
    append_event(events_file, "job_passed", {"job_id": job["id"], "role": args.role})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
