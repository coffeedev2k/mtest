from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import urlopen

import pytest
import yaml

from chartpatch.config import load_config
from tests.e2e_support import (
    ClusterHandle,
    ClusterUnavailable,
    E2E_ENV_VAR,
    REGISTRY_PASSWORD,
    REGISTRY_USERNAME,
    RegistryUnavailable,
    cleanup_helm_release_and_namespace,
    collect_e2e_prerequisite_skip_reasons,
    delete_k3d_cluster,
    e2e_enabled,
    ensure_k3d_cluster,
    ensure_local_registry,
    format_e2e_skip,
    is_localhost_5000_oci_ref,
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
LOCAL_REGISTRY_POLICY = (
    REPO_ROOT / "tests/fixtures/chartpatch/e2e/kyverno/allow-local-registry.yaml"
)
LOCAL_REGISTRY_DEPLOYMENT = (
    REPO_ROOT
    / "tests/fixtures/chartpatch/e2e/kyverno/local-registry-deployment.yaml"
)
EXTERNAL_REGISTRY_POD = (
    REPO_ROOT / "tests/fixtures/chartpatch/e2e/kyverno/external-registry-pod.yaml"
)
POLICY_NAME = "allow-local-registry-only"
TEST_IMAGE_SOURCE = "registry.k8s.io/pause:3.10"
TEST_IMAGE_TARGET = "localhost:5000/chartpatch-e2e/pause:3.10"
KYVERNO_CHART_INDEX = "https://kyverno.github.io/kyverno/index.yaml"


def test_kyverno_e2e_fixture_uses_latest_stable_chart_and_local_registry() -> None:
    config = load_config(KYVERNO_FIXTURE)

    assert config.chart.source.repo == "https://kyverno.github.io/kyverno/"
    assert config.chart.source.chart == "kyverno"
    assert config.chart.source.version == "3.8.1"
    assert config.registry.url == "localhost:5000"
    assert config.registry.username == REGISTRY_USERNAME
    assert config.registry.password == REGISTRY_PASSWORD
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


def test_local_registry_policy_and_workloads_exercise_both_admission_paths() -> None:
    policy = LOCAL_REGISTRY_POLICY.read_text(encoding="utf-8")
    allowed = LOCAL_REGISTRY_DEPLOYMENT.read_text(encoding="utf-8")
    forbidden = EXTERNAL_REGISTRY_POD.read_text(encoding="utf-8")

    assert "failureAction: Enforce" in policy
    assert "kind: ClusterPolicy" in policy
    assert "image: \"localhost:5000/*\"" in policy
    assert f"image: {TEST_IMAGE_TARGET}" in allowed
    assert f"image: {TEST_IMAGE_SOURCE}" in forbidden


def test_chartpatch_plan_kyverno_fixture_reports_latest_stable_inputs() -> None:
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
    assert "Registry authentication: configured" in completed.stdout
    assert REGISTRY_PASSWORD not in completed.stdout
    assert "Output OCI chart reference: oci://localhost:5000/helm/kyverno" in completed.stdout
    assert "  helm_lint: enabled" in completed.stdout
    assert "  helm_template: enabled" in completed.stdout


def _run(
    args: list[str],
    *,
    timeout: int = 300,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        input=input_text,
    )
    if check and completed.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(args)}\n"
            f"exit code: {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _find_installable_chart_ref(
    chart_ref: str,
    chart_name: str,
    version: str,
    registry_config: Path,
) -> str:
    failures: list[str] = []
    for candidate in oci_chart_ref_candidates(chart_ref, chart_name):
        completed = _run(
            [
                "helm",
                "show",
                "chart",
                candidate,
                "--version",
                version,
                "--plain-http",
                "--registry-config",
                str(registry_config),
            ],
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
    cleanup_helm_release_and_namespace(namespace, release)


def _install_kyverno_chart(
    chart_ref: str,
    version: str,
    namespace: str,
    release: str,
    registry_config: Path,
) -> None:
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
            "--plain-http",
            "--registry-config",
            str(registry_config),
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


def _mirror_test_workload_image(auth_file: Path) -> None:
    _run(
        [
            "skopeo",
            "copy",
            "--dest-tls-verify=false",
            "--dest-authfile",
            str(auth_file),
            f"docker://{TEST_IMAGE_SOURCE}",
            f"docker://{TEST_IMAGE_TARGET}",
        ],
        timeout=300,
    )


def _write_registry_auth_file(
    path: Path,
    registry: str,
    username: str,
    password: str,
) -> None:
    token = base64.b64encode(
        f"{username}:{password}".encode("utf-8")
    ).decode("ascii")
    path.write_text(
        json.dumps({"auths": {registry: {"auth": token}}}) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def _helm_registry_login(
    registry: str,
    username: str,
    password: str,
    registry_config: Path,
) -> None:
    _run(
        [
            "helm",
            "registry",
            "login",
            registry,
            "--insecure",
            "--username",
            username,
            "--password-stdin",
            "--registry-config",
            str(registry_config),
        ],
        input_text=f"{password}\n",
    )


def _latest_stable_kyverno_chart_version() -> str:
    with urlopen(KYVERNO_CHART_INDEX, timeout=30) as response:
        index = yaml.safe_load(response)
    for chart in index["entries"]["kyverno"]:
        version = str(chart["version"])
        if "-" not in version:
            return version
    raise AssertionError("official Kyverno chart index contains no stable release")


def _install_local_registry_policy() -> None:
    _run(["kubectl", "apply", "--filename", str(LOCAL_REGISTRY_POLICY)])
    _run(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            f"clusterpolicy/{POLICY_NAME}",
            "--timeout=120s",
        ],
        timeout=180,
    )


def _cleanup_policy_workload(namespace: str) -> None:
    _run(
        [
            "kubectl",
            "delete",
            "clusterpolicy",
            POLICY_NAME,
            "--ignore-not-found=true",
        ],
        check=False,
    )
    _run(
        [
            "kubectl",
            "delete",
            "namespace",
            namespace,
            "--ignore-not-found=true",
            "--wait=true",
        ],
        timeout=180,
        check=False,
    )


def _assert_external_registry_is_rejected(namespace: str) -> None:
    completed = _run(
        [
            "kubectl",
            "apply",
            "--namespace",
            namespace,
            "--filename",
            str(EXTERNAL_REGISTRY_POD),
        ],
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0, (
        "Kyverno unexpectedly admitted a Pod using an external registry\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    assert POLICY_NAME in output


def _deploy_from_local_registry(namespace: str) -> None:
    _run(
        [
            "kubectl",
            "apply",
            "--namespace",
            namespace,
            "--filename",
            str(LOCAL_REGISTRY_DEPLOYMENT),
        ]
    )
    _run(
        [
            "kubectl",
            "rollout",
            "status",
            "deployment/local-registry-smoke",
            "--namespace",
            namespace,
            "--timeout=180s",
        ],
        timeout=240,
    )


@pytest.mark.e2e
def test_chartpatch_sync_kyverno_fixture_installs_from_local_oci_registry() -> None:
    if not e2e_enabled():
        pytest.skip(f"set {E2E_ENV_VAR}=1 to run chartpatch E2E tests")

    skip_reasons = collect_e2e_prerequisite_skip_reasons()
    if skip_reasons:
        pytest.skip(format_e2e_skip(skip_reasons))

    config = load_config(KYVERNO_FIXTURE)
    assert config.chart.source.version == _latest_stable_kyverno_chart_version(), (
        "Kyverno E2E fixture must pin the latest stable chart from "
        f"{KYVERNO_CHART_INDEX}"
    )
    namespace = "chartpatch-kyverno-e2e"
    release = "chartpatch-kyverno"
    workload_namespace = "chartpatch-registry-policy-e2e"
    registry = None
    cluster: ClusterHandle | None = None
    auth_temp_dir = tempfile.TemporaryDirectory(prefix="chartpatch-e2e-auth-")
    auth_root = Path(auth_temp_dir.name)
    skopeo_auth_file = auth_root / "auth.json"
    helm_registry_config = auth_root / "helm-registry.json"
    assert config.registry.username is not None
    assert config.registry.password is not None
    _write_registry_auth_file(
        skopeo_auth_file,
        config.registry.url,
        config.registry.username,
        config.registry.password,
    )
    try:
        registry = ensure_local_registry(
            username=config.registry.username,
            password=config.registry.password,
        )
    except RegistryUnavailable as exc:
        pytest.fail(str(exc))

    try:
        try:
            cluster = ensure_k3d_cluster(
                registry=config.registry.url,
                username=config.registry.username,
                password=config.registry.password,
            )
        except ClusterUnavailable as exc:
            pytest.fail(f"local k3s cluster: {exc}")

        _cleanup_kyverno_release(namespace, release)
        _cleanup_policy_workload(workload_namespace)

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

        _helm_registry_login(
            config.registry.url,
            config.registry.username,
            config.registry.password,
            helm_registry_config,
        )
        install_ref = _find_installable_chart_ref(
            config.chart.output.chart_ref,
            config.chart.name,
            config.chart.source.version,
            helm_registry_config,
        )
        _install_kyverno_chart(
            install_ref,
            config.chart.source.version,
            namespace,
            release,
            helm_registry_config,
        )
        _wait_for_kyverno_workloads(namespace)
        images = _running_kyverno_images(namespace)

        assert images, "expected Kyverno pods to expose container images"
        assert all(
            image.startswith(f"{config.registry.url}/") for image in images
        ), "expected all running Kyverno container images to use the local registry; found: " + (
            ", ".join(images)
        )

        _mirror_test_workload_image(skopeo_auth_file)
        _install_local_registry_policy()
        _run(["kubectl", "create", "namespace", workload_namespace])
        _assert_external_registry_is_rejected(workload_namespace)
        _deploy_from_local_registry(workload_namespace)
    finally:
        if cluster is not None:
            _cleanup_policy_workload(workload_namespace)
            _cleanup_kyverno_release(namespace, release)
            delete_k3d_cluster(cluster)
        if registry is not None:
            stop_local_registry(registry)
        auth_temp_dir.cleanup()
