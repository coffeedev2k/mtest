from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from chartpatch import cli
from chartpatch.config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_CONFIG = REPO_ROOT / "examples/quickstart/kyverno.yaml"
QUICKSTART_PATCH = (
    REPO_ROOT / "examples/quickstart/patches/add-quickstart-annotation.patch"
)
BASE_CONFIG = REPO_ROOT / "chartpatch.yaml"


def test_quickstart_example_is_runnable_and_targets_local_registry() -> None:
    config = load_config(QUICKSTART_CONFIG)

    assert config.registry.url == "localhost:5000"
    assert config.chart.name == "kyverno"
    assert config.chart.source.version == "3.8.1"
    assert config.chart.patch.file == (
        "examples/quickstart/patches/add-quickstart-annotation.patch"
    )
    assert config.chart.output.chart_ref == "oci://localhost:5000/helm/kyverno"
    assert QUICKSTART_PATCH.is_file()
    assert (
        'chartpatch.dev/quickstart: "kyverno-patched"'
        in QUICKSTART_PATCH.read_text(encoding="utf-8")
    )


def test_quickstart_plan_succeeds() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "plan", str(QUICKSTART_CONFIG)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert "Source chart name: kyverno" in completed.stdout
    assert "Source chart version: 3.8.1" in completed.stdout
    assert "Local registry URL: localhost:5000" in completed.stdout
    assert (
        "Output OCI chart reference: oci://localhost:5000/helm/kyverno"
        in completed.stdout
    )


def test_base_config_matches_quickstart() -> None:
    config = load_config(BASE_CONFIG)

    assert config.registry.url == "localhost:5000"
    assert config.chart.name == "kyverno"
    assert config.chart.patch.file == (
        "examples/quickstart/patches/add-quickstart-annotation.patch"
    )


def test_quickrun_starts_registry_before_sync(monkeypatch, capsys) -> None:
    events: list[object] = []

    def fake_check(required=("helm", "git", "skopeo")) -> None:
        events.append(("dependencies", tuple(required)))

    def fake_registry(address: str, **kwargs):
        events.append(("registry", address))
        return SimpleNamespace(
            address=address,
            container_name="chartpatch-registry",
            started=True,
        )

    def fake_sync(chart):
        events.append(("sync", chart.chart_name))
        return object()

    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setattr(cli, "check_required_binaries", fake_check)
    monkeypatch.setattr(cli, "ensure_local_registry", fake_registry)
    monkeypatch.setattr(cli, "run_single_chart_sync", fake_sync)
    monkeypatch.setattr(cli, "render_sync_report", lambda result: "sync complete\n")

    assert cli.main(["quickrun"]) == 0
    assert events == [
        ("dependencies", ("helm", "git", "skopeo", "docker")),
        ("registry", "localhost:5000"),
        ("sync", "kyverno"),
    ]
    assert "Local registry localhost:5000 is started" in capsys.readouterr().out
