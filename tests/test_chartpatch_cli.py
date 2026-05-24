from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from chartpatch import cli
from chartpatch.dependencies import MissingRuntimeDependencies
from chartpatch.runner import CommandRunner
from chartpatch.workflow import (
    STAGE_IMAGE_DISCOVERY,
    STAGE_OCI_PUSH,
    STAGE_PACKAGE,
    SyncResult,
    SyncWorkflowError,
)


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


def test_plan_valid_multi_chart_fixture_exits_zero_and_labels_entries() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "chartpatch",
            "plan",
            str(FIXTURES / "valid-multi-chart.yaml"),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert completed.stderr == ""
    assert "Configured charts: 2" in completed.stdout
    assert "Chart 1: kube-prometheus-stack" in completed.stdout
    assert "Chart 2: kyverno" in completed.stdout
    assert "  Source chart repo: https://kyverno.github.io/kyverno" in completed.stdout
    assert "  Configured patch file: patches/kyverno.patch" in completed.stdout
    assert "  Local registry URL: localhost:5000" in completed.stdout
    assert "  Output OCI chart reference: oci://localhost:5000/helm/kyverno" in (
        completed.stdout
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


def test_plan_invalid_multi_chart_config_exits_nonzero_and_identifies_chart(
    tmp_path: Path,
) -> None:
    config = tmp_path / "invalid-multi-chart.yaml"
    config.write_text(
        """
registry:
  url: localhost:5000

charts:
  - name: kube-prometheus-stack
    source:
      repo: https://prometheus-community.github.io/helm-charts
      chart: kube-prometheus-stack
      version: 70.0.0
    patch:
      file: patches/kube-prometheus-stack.patch
    output:
      chart_ref: oci://localhost:5000/helm/kube-prometheus-stack
    verification:
      helm_lint: true
      helm_template: true
  - name: kyverno
    source:
      repo: https://kyverno.github.io/kyverno
      chart: kyverno
    patch:
      file: patches/kyverno.patch
    output:
      chart_ref: oci://localhost:5000/helm/kyverno
    verification:
      helm_lint: false
      helm_template: true
""".lstrip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "plan", str(config)],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "charts[1] (kyverno)" in completed.stderr
    assert "charts[1].source.version is required" in completed.stderr


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
        raise AssertionError("plan must not run the sync workflow")

    monkeypatch.setattr(cli, "run_sync", fail_if_called)

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


def test_sync_multi_chart_config_fails_before_dependencies_or_workflow(
    monkeypatch,
    capsys,
) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("multi-chart sync must fail before execution")

    monkeypatch.setattr(cli, "check_required_binaries", fail_if_called)
    monkeypatch.setattr(cli, "run_sync", fail_if_called)

    result = cli.main(["sync", str(FIXTURES / "valid-multi-chart.yaml")])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "multi-chart sync is not implemented yet" in captured.err


def test_sync_single_entry_charts_config_is_still_plan_only(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    config = tmp_path / "single-entry-charts.yaml"
    config.write_text(
        """
registry:
  url: localhost:5000

charts:
  - name: kube-prometheus-stack
    source:
      repo: https://prometheus-community.github.io/helm-charts
      chart: kube-prometheus-stack
      version: 70.0.0
    patch:
      file: patches/kube-prometheus-stack.patch
    output:
      chart_ref: oci://localhost:5000/helm/kube-prometheus-stack
    verification:
      helm_lint: true
      helm_template: true
""".lstrip(),
        encoding="utf-8",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("top-level charts config must fail before execution")

    monkeypatch.setattr(cli, "check_required_binaries", fail_if_called)
    monkeypatch.setattr(cli, "run_sync", fail_if_called)

    result = cli.main(["sync", str(config)])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "multi-chart sync is not implemented yet" in captured.err


def test_sync_valid_fixture_exits_nonzero_when_dependency_is_missing(monkeypatch, capsys) -> None:
    def fail_with_missing_dependency() -> None:
        raise MissingRuntimeDependencies(("skopeo",))

    monkeypatch.setattr(cli, "check_required_binaries", fail_with_missing_dependency)

    result = cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "Failed stage: dependency check" in captured.err
    assert "missing required runtime dependency: skopeo" in captured.err


def test_sync_valid_fixture_exits_zero_and_prints_report(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "check_required_binaries", lambda: None)
    monkeypatch.setattr(
        cli,
        "run_sync",
        lambda config: SyncResult(
            source_repo=config.chart.source.repo,
            source_chart=config.chart.source.chart,
            source_version=config.chart.source.version,
            patch_file=config.chart.patch.file,
            registry_url=config.registry.url,
            output_chart_ref=config.chart.output.chart_ref,
            workspace_path=Path("tmp/chartpatch-sync-test"),
            chart_archive_path=Path(
                "tmp/chartpatch-sync-test/downloaded/kube-prometheus-stack-70.0.0.tgz"
            ),
            unpacked_chart_path=Path(
                "tmp/chartpatch-sync-test/unpacked/kube-prometheus-stack"
            ),
            original_render_path=Path(
                "tmp/chartpatch-sync-test/rendered/original.yaml"
            ),
            discovered_images=(
                "docker.io/bitnami/nginx:1.27.4",
                "registry.example.com/setup:1.0.0",
            ),
        ),
    )

    result = cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out == (
        "ChartPatch sync report\n"
        "Source chart repo: https://prometheus-community.github.io/helm-charts\n"
        "Source chart name: kube-prometheus-stack\n"
        "Source chart version: 70.0.0\n"
        "Configured patch file: patches/kube-prometheus-stack.patch\n"
        "Local registry URL: localhost:5000\n"
        "Output OCI chart reference: oci://localhost:5000/helm/kube-prometheus-stack\n"
        "Workspace path: tmp/chartpatch-sync-test\n"
        "Pulled chart archive: tmp/chartpatch-sync-test/downloaded/kube-prometheus-stack-70.0.0.tgz\n"
        "Unpacked chart path: tmp/chartpatch-sync-test/unpacked/kube-prometheus-stack\n"
        "Original render output: tmp/chartpatch-sync-test/rendered/original.yaml\n"
        "Discovered images: 2\n"
        "  - docker.io/bitnami/nginx:1.27.4\n"
        "  - registry.example.com/setup:1.0.0\n"
        "Image mirroring summary:\n"
        "  Mirrored images: 0\n"
        "Patch application status: skipped\n"
        "Image rewrite verification status: skipped\n"
        "Final helm lint verification: skipped\n"
        "Final helm template verification: skipped\n"
        "Overall status: success\n"
    )


def test_sync_no_discovered_images_exits_nonzero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "check_required_binaries", lambda: None)

    def fail_with_no_images(config) -> SyncResult:
        raise SyncWorkflowError(
            "image discovery failed: rendered manifests contain no discoverable container images",
            stage=STAGE_IMAGE_DISCOVERY,
            source_repo=config.chart.source.repo,
            source_chart=config.chart.source.chart,
            source_version=config.chart.source.version,
        )

    monkeypatch.setattr(cli, "run_sync", fail_with_no_images)

    result = cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "Failed stage: image discovery" in captured.err
    assert "no discoverable container images" in captured.err


@pytest.mark.parametrize(
    ("stage", "message", "expected_stage"),
    [
        (
            STAGE_PACKAGE,
            "helm package failed: helm package chart --destination packages exited with code 44\n"
            "stderr:\npackage denied",
            "package",
        ),
        (
            STAGE_OCI_PUSH,
            "helm push failed: helm push chart.tgz oci://localhost:5000/helm/chart "
            "exited with code 45\nstderr:\npush denied",
            "OCI push",
        ),
    ],
)
def test_sync_late_stage_failures_exit_nonzero_with_structured_report(
    monkeypatch,
    capsys,
    stage: str,
    message: str,
    expected_stage: str,
) -> None:
    monkeypatch.setattr(cli, "check_required_binaries", lambda: None)

    def fail_sync(config) -> SyncResult:
        raise SyncWorkflowError(
            message,
            stage=stage,
            source_repo=config.chart.source.repo,
            source_chart=config.chart.source.chart,
            source_version=config.chart.source.version,
            workspace_path=Path("tmp/chartpatch-sync-failed"),
        )

    monkeypatch.setattr(cli, "run_sync", fail_sync)

    result = cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "ChartPatch sync failed" in captured.err
    assert f"Failed stage: {expected_stage}" in captured.err
    assert "Source chart repo: https://prometheus-community.github.io/helm-charts" in (
        captured.err
    )
    assert "Source chart name: kube-prometheus-stack" in captured.err
    assert "Source chart version: 70.0.0" in captured.err
    assert "Workspace path: tmp/chartpatch-sync-failed" in captured.err
    assert message in captured.err


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


def test_sync_missing_dependency_fails_before_workflow_execution(monkeypatch, capsys) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("missing dependency must not run the sync workflow")

    def fail_with_missing_dependency() -> None:
        raise MissingRuntimeDependencies(("helm",))

    monkeypatch.setattr(cli, "run_sync", fail_if_called)
    monkeypatch.setattr(cli, "check_required_binaries", fail_with_missing_dependency)

    assert cli.main(["sync", str(FIXTURES / "valid-kube-prometheus-stack.yaml")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Failed stage: dependency check" in captured.err
    assert "missing required runtime dependency: helm" in captured.err


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
