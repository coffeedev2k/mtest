from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import FactoryConfig


@dataclass(frozen=True)
class BackendResult:
    returncode: int
    stdout: str
    stderr: str
    outputs: dict[str, str]


def run_backend(
    config: FactoryConfig,
    repo_root: Path,
    run_dir: Path,
    role: str,
    job: dict[str, Any],
) -> BackendResult:
    if config.backend == "fake_planner":
        return _run_fake_planner(run_dir, job)
    if config.backend == "codex_exec":
        return _run_codex_exec(config, repo_root, run_dir, role, job)
    raise ValueError(f"unsupported backend: {config.backend}")


def _run_fake_planner(run_dir: Path, job: dict[str, Any]) -> BackendResult:
    plan = "\n".join(
            [
                "# Plan",
                "",
                f"Job: {job['id']}",
                "",
                "1. Restate the product goal.",
                "2. Generate small implementation tasks.",
                "3. Require unit, regression, and e2e gates.",
                "",
            ]
    )
    return BackendResult(returncode=0, stdout="fake planner generated plan.md\n", stderr="", outputs={"plan.md": plan})


def _run_codex_exec(
    config: FactoryConfig,
    repo_root: Path,
    run_dir: Path,
    role: str,
    job: dict[str, Any],
) -> BackendResult:
    prompt = _render_prompt(repo_root, run_dir, role, job)
    output_capture = run_dir / "agents" / f"{role}.{job['id']}.last-message.md"
    args = [
        item.format(repo=str(repo_root), run=str(run_dir), role=role, job=job["id"])
        for item in config.backend_config.args
    ]
    command = [
        config.backend_config.command,
        *args,
        "--sandbox",
        "read-only",
        "-o",
        str(output_capture),
        prompt,
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    outputs = {}
    if completed.returncode == 0 and output_capture.exists():
        outputs["plan.md"] = output_capture.read_text(encoding="utf-8")
    return BackendResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        outputs=outputs,
    )


def _render_prompt(repo_root: Path, run_dir: Path, role: str, job: dict[str, Any]) -> str:
    if role != "planner":
        raise ValueError(f"no prompt renderer for role: {role}")
    prompt_path = repo_root / "agents" / "planner.md"
    template = prompt_path.read_text(encoding="utf-8")
    return template.format(
        repo=repo_root,
        run=run_dir,
        job_id=job["id"],
        feature=run_dir / "input" / "feature.md",
        config=run_dir / "input" / "factory.yaml",
        output=run_dir / "plan.md",
    )
