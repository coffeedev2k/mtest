from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chartpatch import cli
from chartpatch.dependencies import MissingRuntimeDependencies
from chartpatch.runner import CommandRunner


FIXTURES = Path("tests/fixtures/chartpatch")


def test_plan_valid_fixture_exits_zero_and_emits_stable_output() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "chartpatch",
            "plan",
            str(FIXTURES / "valid-kube-prometheus-stack.yaml"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert completed.stderr == ""
    assert completed.stdout == (
        "ChartPatch execution plan\n"
        "Configured chart name: kube-prometheus-stack\n"
        "Source chart repo: https://prometheus-community.github.io/helm-charts\n"
        "Source chart name: kube-prometheus-stack\n"
        "Source chart version: 70.0.0\n"
        "Configured patch file: patches/kube-prometheus-stack.patch\n"
        "Local registry URL: localhost:5000\n"
        "Output OCI chart reference: oci://localhost:5000/helm/kube-prometheus-stack\n"
        "Verification steps:\n"
        "  helm_lint: enabled\n"
        "  helm_template: enabled\n"
        "No remote mutation: plan only reads the config and prints this plan.\n"
    )


def test_plan_invalid_fixture_exits_nonzero_and_emits_useful_stderr() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "chartpatch",
            "plan",
            str(FIXTURES / "missing-source-version.yaml"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "chart.source.version is required" in completed.stderr


def test_plan_missing_config_file_exits_nonzero() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "plan", str(FIXTURES / "missing.yaml")],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "config file not found" in completed.stderr


def test_plan_invalid_yaml_exits_nonzero(tmp_path: Path) -> None:
    config = tmp_path / "invalid.yaml"
    config.write_text("chart:\n  source: [broken\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "plan", str(config)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "invalid YAML" in completed.stderr


def test_plan_does_not_invoke_command_runner(monkeypatch, capsys) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("plan must not invoke the command runner")

    monkeypatch.setattr(CommandRunner, "run", fail_if_called)

    assert cli.main(["plan", str(FIXTURES / "valid-kube-prometheus-stack.yaml")]) == 0
    captured = capsys.readouterr()
    assert "ChartPatch execution plan" in captured.out
    assert captured.err == ""


def test_plan_does_not_invoke_sync_workflow(monkeypatch, capsys) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("plan must not render the sync summary")

    monkeypatch.setattr(cli, "build_sync_summary", fail_if_called)

    assert cli.main(["plan", str(FIXTURES / "valid-kube-prometheus-stack.yaml")]) == 0
    captured = capsys.readouterr()
    assert "ChartPatch execution plan" in captured.out
    assert captured.err == ""


def test_plan_does_not_check_sync_runtime_dependencies(monkeypatch, capsys) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("plan must not check sync runtime dependencies")

    monkeypatch.setattr(cli, "check_required_binaries", fail_if_called)

    assert cli.main(["plan", str(FIXTURES / "valid-kube-prometheus-stack.yaml")]) == 0

    captured = capsys.readouterr()
    assert "ChartPatch execution plan" in captured.out
    assert captured.err == ""


def test_sync_invalid_fixture_fails_before_workflow_execution(monkeypatch, capsys) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid config must not check runtime dependencies")

    monkeypatch.setattr(cli, "check_required_binaries", fail_if_called)

    result = cli.main(["sync", str(FIXTURES / "missing-source-version.yaml")])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "chart.source.version is required" in captured.err


def test_sync_valid_fixture_exits_nonzero_when_dependency_is_missing(monkeypatch, capsys) -> None:
    def fail_with_missing_dependency() -> None:
        raise MissingRuntimeDependencies(("skopeo",))

    monkeypatch.setattr(cli, "check_required_binaries", fail_with_missing_dependency)

    result = cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "missing required runtime dependency: skopeo" in captured.err


def test_sync_valid_fixture_exits_zero_and_prints_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "check_required_binaries", lambda: None)

    result = cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out == (
        "ChartPatch sync summary\n"
        "Source chart repo: https://prometheus-community.github.io/helm-charts\n"
        "Source chart name: kube-prometheus-stack\n"
        "Source chart version: 70.0.0\n"
        "Patch file: patches/kube-prometheus-stack.patch\n"
        "Local registry URL: localhost:5000\n"
        "Output OCI chart reference: oci://localhost:5000/helm/kube-prometheus-stack\n"
        "Planned sync stages:\n"
        "  1. pull chart\n"
        "  2. render original chart\n"
        "  3. discover images\n"
        "  4. mirror images\n"
        "  5. apply patch\n"
        "  6. rewrite images\n"
        "  7. verify patched chart\n"
        "  8. package chart\n"
        "  9. push chart\n"
        "No remote mutation: sync only checks dependencies and prints this summary.\n"
    )


def test_sync_invalid_fixture_reports_plan_consistent_validation_error() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "chartpatch",
            "sync",
            str(FIXTURES / "missing-source-version.yaml"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "chart.source.version is required" in completed.stderr


def test_sync_does_not_invoke_command_runner(monkeypatch, capsys) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("sync skeleton must not invoke the command runner")

    monkeypatch.setattr(CommandRunner, "run", fail_if_called)
    monkeypatch.setattr(cli, "check_required_binaries", lambda: None)

    assert cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")]) == 0
    captured = capsys.readouterr()
    assert "ChartPatch sync summary" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("command", ["plan", "sync"])
def test_missing_command_argument_exits_nonzero(command: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", command],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "config" in completed.stderr


def test_missing_plan_argument_exits_nonzero() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "plan"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "config" in completed.stderr


def test_missing_sync_argument_exits_nonzero() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "sync"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "config" in completed.stderr


def test_unknown_command_exits_nonzero() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "unknown"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr
