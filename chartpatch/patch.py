from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .runner import CommandResult, CommandRunner


class PatchApplicationError(RuntimeError):
    """Raised when a configured chart patch cannot be applied cleanly."""


PatchCommandCallback = Callable[[str, CommandResult], None]


@dataclass(frozen=True)
class AppliedPatch:
    patch_file: Path
    chart_dir: Path


def apply_patch_file(
    chart_dir: Path,
    patch_file: Path,
    runner: CommandRunner,
    *,
    on_result: PatchCommandCallback | None = None,
) -> AppliedPatch:
    _run_required(
        runner,
        ["git", "init"],
        chart_dir,
        "git init failed",
        on_result,
        "git-init",
    )
    _run_required(
        runner,
        ["git", "config", "user.name", "ChartPatch"],
        chart_dir,
        "git user.name config failed",
        on_result,
        "git-config-user-name",
    )
    _run_required(
        runner,
        ["git", "config", "user.email", "chartpatch@example.invalid"],
        chart_dir,
        "git user.email config failed",
        on_result,
        "git-config-user-email",
    )
    _run_required(
        runner,
        ["git", "add", "--all"],
        chart_dir,
        "git add failed",
        on_result,
        "git-add",
    )
    _run_required(
        runner,
        ["git", "commit", "-m", "Baseline upstream chart"],
        chart_dir,
        "git baseline commit failed",
        on_result,
        "git-commit-baseline",
    )

    _run_required(
        runner,
        ["git", "am", "--reject", str(patch_file)],
        chart_dir,
        "patch application failed",
        on_result,
        "git-am",
    )

    reject_files = _find_reject_files(chart_dir)
    if reject_files:
        formatted = "\n".join(f"  - {path}" for path in reject_files)
        raise PatchApplicationError(
            f"patch application failed: reject files remain\n{formatted}"
        )

    rebase_apply = chart_dir / ".git" / "rebase-apply"
    if rebase_apply.exists():
        raise PatchApplicationError(
            f"patch application failed: unfinished git am state remains at {rebase_apply}"
        )

    return AppliedPatch(patch_file=patch_file, chart_dir=chart_dir)


def _run_required(
    runner: CommandRunner,
    args: list[str],
    cwd: Path,
    failure_label: str,
    on_result: PatchCommandCallback | None,
    log_label: str,
) -> CommandResult:
    result = runner.run(args, cwd=cwd)
    if on_result is not None:
        on_result(log_label, result)
    if result.returncode != 0:
        raise PatchApplicationError(_format_command_failure(failure_label, result))
    return result


def _find_reject_files(chart_dir: Path) -> tuple[Path, ...]:
    reject_files = sorted(path for path in chart_dir.rglob("*.rej") if path.is_file())
    return tuple(_relative_to(path, chart_dir) for path in reject_files)


def _relative_to(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _format_command_failure(label: str, result: CommandResult) -> str:
    lines = [
        f"{label}: {' '.join(result.args)} exited with code {result.returncode}",
    ]
    if result.stdout.strip():
        lines.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr.strip():
        lines.append(f"stderr:\n{result.stderr.rstrip()}")
    return "\n".join(lines)
