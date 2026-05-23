from __future__ import annotations

from pathlib import Path

from chartpatch.helm import (
    helm_lint_args,
    helm_package_args,
    helm_push_args,
    helm_template_args,
    run_helm_lint,
    run_helm_package,
    run_helm_push,
    run_helm_template,
    validate_oci_chart_ref,
)
from chartpatch.runner import CommandResult


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: list[str]) -> CommandResult:
        call = tuple(args)
        self.calls.append(call)
        return CommandResult(call, 0, "ok\n", "")


def test_helm_lint_command_construction() -> None:
    assert helm_lint_args(Path("/tmp/chart")) == [
        "helm",
        "lint",
        "/tmp/chart",
    ]


def test_final_helm_template_verification_command_construction() -> None:
    assert helm_template_args("release-name", Path("/tmp/chart")) == [
        "helm",
        "template",
        "release-name",
        "/tmp/chart",
    ]


def test_helm_package_command_construction() -> None:
    assert helm_package_args(Path("/tmp/chart"), Path("/tmp/packages")) == [
        "helm",
        "package",
        "/tmp/chart",
        "--destination",
        "/tmp/packages",
    ]


def test_helm_push_command_construction() -> None:
    assert helm_push_args(
        Path("/tmp/packages/chart-1.0.0.tgz"),
        "oci://localhost:5000/helm/chart",
    ) == [
        "helm",
        "push",
        "/tmp/packages/chart-1.0.0.tgz",
        "oci://localhost:5000/helm/chart",
    ]


def test_helm_push_rejects_non_oci_chart_ref() -> None:
    try:
        validate_oci_chart_ref("http://localhost:5000/helm/chart")
    except ValueError as exc:
        assert "chart.output.chart_ref must start with oci://" in str(exc)
    else:
        raise AssertionError("expected non-OCI chart ref to fail validation")


def test_run_helm_lint_uses_runner() -> None:
    runner = RecordingRunner()

    result = run_helm_lint(runner, Path("/tmp/chart"))

    assert result.returncode == 0
    assert runner.calls == [("helm", "lint", "/tmp/chart")]


def test_run_helm_template_uses_runner() -> None:
    runner = RecordingRunner()

    result = run_helm_template(runner, "release-name", Path("/tmp/chart"))

    assert result.returncode == 0
    assert runner.calls == [("helm", "template", "release-name", "/tmp/chart")]


def test_run_helm_package_uses_runner() -> None:
    runner = RecordingRunner()

    result = run_helm_package(runner, Path("/tmp/chart"), Path("/tmp/packages"))

    assert result.returncode == 0
    assert runner.calls == [
        ("helm", "package", "/tmp/chart", "--destination", "/tmp/packages")
    ]


def test_run_helm_push_uses_runner() -> None:
    runner = RecordingRunner()

    result = run_helm_push(
        runner,
        Path("/tmp/packages/chart-1.0.0.tgz"),
        "oci://localhost:5000/helm/chart",
    )

    assert result.returncode == 0
    assert runner.calls == [
        (
            "helm",
            "push",
            "/tmp/packages/chart-1.0.0.tgz",
            "oci://localhost:5000/helm/chart",
        )
    ]
