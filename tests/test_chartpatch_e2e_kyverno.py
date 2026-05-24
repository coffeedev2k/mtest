from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from chartpatch.config import load_config
from tests.e2e_support import (
    ClusterHandle,
    ClusterUnavailable,
    E2E_ENV_VAR,
    RegistryUnavailable,
    delete_k3d_cluster,
    e2e_enabled,
    ensure_k3d_cluster,
    ensure_local_registry,
    is_localhost_5000_oci_ref,
    missing_required_tools,
    oci_chart_ref_candidates,
    pod_container_images,
    stop_local_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
KYVERNO_FIXTURE = REPO_ROOT / "tests/fixtures/chartpatch/e2e/kyverno/config.yaml"
KYVERNO_PATCH = (
    REPO_ROOT
    / "tests/fixtures/chartpatch/e2e/kyverno/patches/add-fixture-annotation.patch"
)


def test_kyverno_e2e_fixture_is_pinned_and_targets_local_registry() -> None:
    config = load_config(KYVERNO_FIXTURE)

    assert config.chart.source.repo == "https://kyverno.github.io/kyverno/"
    assert config.chart.source.chart == "kyverno"
    assert config.chart.source.version == "3.8.1"
    assert config.registry.url == "localhost:5000"
    assert is_localhost_5000_oci_ref(config.chart.output.chart_ref)
    assert config.chart.output.chart_ref == "oci://localhost:5000/helm/kyverno"
    assert config.chart.patch.file == (
        "tests/fixtures/chartpatch/e2e/kyverno/patches/add-fixture-annotation.patch"
    )
    assert config.chart.verification.helm_lint is True
    assert config.chart.verification.helm_template is True

    patch_text = KYVERNO_PATCH.read_text(encoding="utf-8")
    assert patch_text.startswith("From ")
    assert 'chartpatch.dev/fixture: "kyverno-e2e-pinned"' in patch_text


def test_chartpatch_plan_kyverno_fixture_reports_pinned_inputs() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "chartpatch", "plan", str(KYVERNO_FIXTURE)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert "Source chart repo: https://kyverno.github.io/kyverno/" in completed.stdout
    assert "Source chart name: kyverno" in completed.stdout
    assert "Source chart version: 3.8.1" in completed.stdout
    assert (
        "Configured patch file: "
        "tests/fixtures/chartpatch/e2e/kyverno/patches/add-fixture-annotation.patch"
        in completed.stdout
    )
    assert "Local registry URL: localhost:5000" in completed.stdout
    assert "Output OCI chart reference: oci://localhost:5000/helm/kyverno" in completed.stdout
    assert "  helm_lint: enabled" in completed.stdout
    assert "  helm_template: enabled" in completed.stdout


def _run(
    args: list[str],
    *,
    timeout: int = 300,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(args)}\n"
            f"exit code: {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _find_installable_chart_ref(chart_ref: str, chart_name: str, version: str) -> str:
    failures: list[str] = []
    for candidate in oci_chart_ref_candidates(chart_ref, chart_name):
        completed = _run(
            ["helm", "show", "chart", candidate, "--version", version],
            timeout=120,
            check=False,
        )
        if completed.returncode == 0:
            return candidate
        failures.append(
            f"{candidate}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    raise AssertionError(
        "pushed chart was not pullable from any expected OCI reference:\n"
        + "\n".join(failures)
    )


def _cleanup_kyverno_release(namespace: str, release: str) -> None:
    _run(
        ["helm", "uninstall", release, "--namespace", namespace, "--ignore-not-found"],
        timeout=180,
        check=False,
    )
    _run(
        ["kubectl", "delete", "namespace", namespace, "--ignore-not-found=true"],
        timeout=180,
        check=False,
    )


def _install_kyverno_chart(chart_ref: str, version: str, namespace: str, release: str) -> None:
    _run(
        [
            "helm",
            "install",
            release,
            chart_ref,
            "--version",
            version,
            "--namespace",
            namespace,
            "--create-namespace",
            "--wait",
            "--timeout",
            "10m",
        ],
        timeout=720,
    )


def _wait_for_kyverno_workloads(namespace: str) -> None:
    _run(
        [
            "kubectl",
            "wait",
            "--for=condition=Available",
            "deployment",
            "--all",
            "--namespace",
            namespace,
            "--timeout=300s",
        ],
        timeout=360,
    )
    _run(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "pod",
            "--all",
            "--namespace",
            namespace,
            "--timeout=300s",
        ],
        timeout=360,
    )


def _running_kyverno_images(namespace: str) -> tuple[str, ...]:
    pods = _run(
        [
            "kubectl",
            "get",
            "pods",
            "--namespace",
            namespace,
            "--output",
            "json",
        ],
        timeout=120,
    )
    return pod_container_images(pods.stdout)


@pytest.mark.e2e
def test_chartpatch_sync_kyverno_fixture_installs_from_local_oci_registry() -> None:
    if not e2e_enabled():
        pytest.skip(f"set {E2E_ENV_VAR}=1 to run chartpatch E2E tests")

    missing = missing_required_tools()
    if missing:
        pytest.skip(f"missing E2E dependency: {', '.join(missing)}")

    config = load_config(KYVERNO_FIXTURE)
    namespace = "chartpatch-kyverno-e2e"
    release = "chartpatch-kyverno"
    registry = None
    cluster: ClusterHandle | None = None
    try:
        registry = ensure_local_registry()
    except RegistryUnavailable as exc:
        pytest.skip(f"missing E2E dependency: {exc}")

    try:
        try:
            cluster = ensure_k3d_cluster(registry=config.registry.url)
        except ClusterUnavailable as exc:
            pytest.skip(f"missing E2E dependency: {exc}")

        _cleanup_kyverno_release(namespace, release)

        completed = _run(
            [sys.executable, "-m", "chartpatch", "sync", str(KYVERNO_FIXTURE)],
            timeout=900,
            check=False,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode == 0, (
            "chartpatch sync failed\n"
            f"exit code: {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
        assert "Discovered images:" in output
        assert "Image target mappings:" in output
        assert "localhost:5000/" in output
        assert "Image mirroring summary:" in output
        assert "Mirrored images:" in output
        assert "Patch application status: passed" in output
        assert "Image rewrites:" in output
        assert "Image rewrite verification status: passed" in output
        assert "Packaged chart:" in output
        assert "Pushed OCI chart reference: oci://localhost:5000/helm/kyverno" in output
        assert "Overall status: success" in output

        install_ref = _find_installable_chart_ref(
            config.chart.output.chart_ref,
            config.chart.name,
            config.chart.source.version,
        )
        _install_kyverno_chart(
            install_ref,
            config.chart.source.version,
            namespace,
            release,
        )
        _wait_for_kyverno_workloads(namespace)
        images = _running_kyverno_images(namespace)

        assert images, "expected Kyverno pods to expose container images"
        assert all(
            image.startswith(f"{config.registry.url}/") for image in images
        ), "expected all running Kyverno container images to use the local registry; found: " + (
            ", ".join(images)
        )
    finally:
        _cleanup_kyverno_release(namespace, release)
        if cluster is not None:
            delete_k3d_cluster(cluster)
        if registry is not None:
            stop_local_registry(registry)
