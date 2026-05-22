from __future__ import annotations

from pathlib import Path

from .jsonio import read_json


def render_status(run_dir: Path) -> str:
    state = read_json(run_dir / "state.json")
    queue = read_json(run_dir / "queue.json")
    lines = [
        f"run: {state.get('run_id', run_dir.name)}",
        f"status: {state.get('status', 'unknown')}",
        f"backend: {state.get('backend', 'unknown')}",
        "jobs:",
    ]
    for job in queue.get("jobs", []):
        detail = f"  - {job.get('id')}: {job.get('role')} -> {job.get('status')}"
        if job.get("lease_owner"):
            detail += f" ({job['lease_owner']})"
        if job.get("error"):
            detail += f" error={job['error']}"
        lines.append(detail)
    blocked_reason = state.get("blocked_reason")
    if blocked_reason:
        lines.append(f"blocked_reason: {blocked_reason}")
    return "\n".join(lines) + "\n"
