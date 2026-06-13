from __future__ import annotations

from pathlib import Path

from chartpatch.helm import (
    helm_lint_args,
    helm_package_args,
    helm_pull_args,
    helm_push_args,
    helm_registry_login_args,
    helm_template_args,
    run_helm_lint,
    run_helm_package,
    run_helm_pull,
    run_helm_push,
    run_helm_registry_login,
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


def test_helm_pull_http_repository_command_construction() -> None:
    assert helm_pull_args(
        "https://charts.example.test",
        "example",
        "1.2.3",
        Path("/tmp/charts"),
    ) == [
        "helm",
        "pull",
        "example",
        "--repo",
        "https://charts.example.test",
        "--version",
        "1.2.3",
        "--destination",
        "/tmp/charts",
    ]


def test_helm_pull_oci_repository_command_construction() -> None:
    assert helm_pull_args(
        "oci://public.ecr.aws/karpenter",
        "karpenter",
        "1.11.1",
        Path("/tmp/charts"),
    ) == [
        "helm",
        "pull",
        "oci://public.ecr.aws/karpenter/karpenter",
        "--version",
        "1.11.1",
        "--destination",
        "/tmp/charts",
    ]


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


def test_helm_template_and_lint_include_configured_values() -> None:
    values = (
        ("settings.clusterName", "chartpatch-example"),
        ("feature.enabled", "true"),
    )

    assert helm_template_args("release-name", Path("/tmp/chart"), values)[-4:] == [
        "--set-string",
        "settings.clusterName=chartpatch-example",
        "--set-string",
        "feature.enabled=true",
    ]
    assert helm_lint_args(Path("/tmp/chart"), values)[-4:] == [
        "--set-string",
        "settings.clusterName=chartpatch-example",
        "--set-string",
        "feature.enabled=true",
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
        "--plain-http",
    ]


def test_helm_registry_login_uses_password_stdin() -> None:
    assert helm_registry_login_args(
        "localhost:5000",
        "chartpatch",
        Path("/tmp/registry.json"),
    ) == [
        "helm",
        "registry",
        "login",
        "localhost:5000",
        "--insecure",
        "--username",
        "chartpatch",
        "--password-stdin",
        "--registry-config",
        "/tmp/registry.json",
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


def test_run_helm_pull_uses_runner() -> None:
    runner = RecordingRunner()

    result = run_helm_pull(
        runner,
        "oci://docker.io/envoyproxy",
        "gateway-helm",
        "v1.8.0",
        Path("/tmp/charts"),
    )

    assert result.returncode == 0
    assert runner.calls == [
        (
            "helm",
            "pull",
            "oci://docker.io/envoyproxy/gateway-helm",
            "--version",
            "v1.8.0",
            "--destination",
            "/tmp/charts",
        )
    ]


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
            "--plain-http",
        )
    ]


def test_run_helm_registry_login_does_not_put_password_in_args() -> None:
    class LoginRunner:
        def __init__(self) -> None:
            self.args: tuple[str, ...] = ()
            self.input_text = ""

        def run(self, args, *, input_text=None):
            self.args = tuple(args)
            self.input_text = input_text
            return CommandResult(self.args, 0, "Login Succeeded\n", "")

    runner = LoginRunner()
    result = run_helm_registry_login(
        runner,
        "localhost:5000",
        "chartpatch",
        "secret-password",
        Path("/tmp/registry.json"),
    )

    assert result.returncode == 0
    assert "secret-password" not in runner.args
    assert runner.input_text == "secret-password\n"
