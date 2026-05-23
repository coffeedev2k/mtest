from __future__ import annotations

from pathlib import Path

from chartpatch.helm import (
    helm_lint_args,
    helm_template_args,
    run_helm_lint,
    run_helm_template,
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
