from __future__ import annotations

from pathlib import Path

from .runner import CommandResult, CommandRunner


def helm_lint_args(chart_dir: Path) -> list[str]:
    return ["helm", "lint", str(chart_dir)]


def helm_template_args(release_name: str, chart_dir: Path) -> list[str]:
    return ["helm", "template", release_name, str(chart_dir)]


def helm_package_args(chart_dir: Path, destination_dir: Path) -> list[str]:
    return ["helm", "package", str(chart_dir), "--destination", str(destination_dir)]


def validate_oci_chart_ref(chart_ref: str) -> None:
    if not chart_ref.startswith("oci://"):
        raise ValueError(
            "chart.output.chart_ref must start with oci:// for helm push: "
            f"{chart_ref}"
        )


def helm_push_args(packaged_chart_path: Path, chart_ref: str) -> list[str]:
    validate_oci_chart_ref(chart_ref)
    return ["helm", "push", str(packaged_chart_path), chart_ref]


def run_helm_lint(runner: CommandRunner, chart_dir: Path) -> CommandResult:
    return runner.run(helm_lint_args(chart_dir))


def run_helm_template(
    runner: CommandRunner,
    release_name: str,
    chart_dir: Path,
) -> CommandResult:
    return runner.run(helm_template_args(release_name, chart_dir))


def run_helm_package(
    runner: CommandRunner,
    chart_dir: Path,
    destination_dir: Path,
) -> CommandResult:
    return runner.run(helm_package_args(chart_dir, destination_dir))


def run_helm_push(
    runner: CommandRunner,
    packaged_chart_path: Path,
    chart_ref: str,
) -> CommandResult:
    return runner.run(helm_push_args(packaged_chart_path, chart_ref))
