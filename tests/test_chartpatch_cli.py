from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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


def test_missing_plan_argument_exits_nonzero() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "plan"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "config" in completed.stderr


def test_unknown_command_exits_nonzero() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "sync"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode != 0
    assert "invalid choice" in completed.stderr
