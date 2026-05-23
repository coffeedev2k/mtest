from __future__ import annotations

from pathlib import Path

from .runner import CommandResult, CommandRunner


def helm_lint_args(chart_dir: Path) -> list[str]:
    return ["helm", "lint", str(chart_dir)]


def helm_template_args(release_name: str, chart_dir: Path) -> list[str]:
    return ["helm", "template", release_name, str(chart_dir)]


def run_helm_lint(runner: CommandRunner, chart_dir: Path) -> CommandResult:
    return runner.run(helm_lint_args(chart_dir))


def run_helm_template(
    runner: CommandRunner,
    release_name: str,
    chart_dir: Path,
) -> CommandResult:
    return runner.run(helm_template_args(release_name, chart_dir))
