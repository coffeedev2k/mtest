from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from tests.e2e_support import (
    E2E_ENV_VAR,
    K3S_IMAGE,
    LOCAL_REGISTRY,
    cleanup_helm_release_and_namespace,
    collect_e2e_prerequisite_skip_reasons,
    container_runtime_skip_reason,
    e2e_enabled,
    first_available_runtime,
    format_e2e_skip,
    is_localhost_5000_oci_ref,
    k3d_registry_config,
    local_k3s_skip_reason,
    missing_required_tools,
    network_skip_reasons,
    oci_chart_ref_candidates,
    pod_container_images,
    registry_api_url,
    registry_port,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_e2e_enabled_requires_explicit_one() -> None:
    assert e2e_enabled({E2E_ENV_VAR: "1"}) is True
    assert e2e_enabled({E2E_ENV_VAR: "true"}) is False
    assert e2e_enabled({}) is False


def test_missing_required_tools_reports_only_unavailable_tools() -> None:
    available = {"helm": "/usr/bin/helm"}

    missing = missing_required_tools(
        required=("helm", "skopeo", "docker"),
        which=available.get,
    )

    assert missing == ("skopeo", "docker")


def test_missing_executables_are_named_in_skip_reason() -> None:
    reasons = collect_e2e_prerequisite_skip_reasons(
        required=("helm", "skopeo", "k3d"),
        runtimes=(),
        which={}.get,
        run=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
        open_url=lambda *args, **kwargs: _FakeResponse(200),
    )

    assert "executable check: helm: executable not found on PATH" in reasons
    assert "executable check: skopeo: executable not found on PATH" in reasons
    assert (
        "executable check: local k3s cluster manager (k3d): executable not found on PATH"
        in reasons
    )


def test_first_available_runtime_preserves_preference_order() -> None:
    available = {"podman": "/usr/bin/podman", "nerdctl": "/usr/bin/nerdctl"}

    assert first_available_runtime(
        runtimes=("docker", "podman", "nerdctl"),
        which=available.get,
    ) == "podman"


def test_unavailable_container_runtime_is_named_in_skip_reason() -> None:
    reason = container_runtime_skip_reason(
        runtimes=("docker", "podman"),
        which={"docker": "/usr/bin/docker"}.get,
        run=lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stderr="Cannot connect to the Docker daemon",
        ),
    )

    assert reason is not None
    assert reason.startswith("container runtime check: docker:")
    assert "Cannot connect to the Docker daemon" in reason


def test_missing_container_runtime_reports_supported_runtime_names() -> None:
    reason = container_runtime_skip_reason(
        runtimes=("docker", "podman"),
        which={}.get,
    )

    assert reason == (
        "container runtime check: Docker-compatible runtime: "
        "none found on PATH (docker, podman)"
    )


def test_unavailable_k3s_cluster_manager_is_named_in_skip_reason() -> None:
    reason = local_k3s_skip_reason(
        run=lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            1,
            stderr="permission denied opening docker socket",
        )
    )

    assert reason is not None
    assert reason.startswith("local k3s cluster check: k3d:")
    assert "permission denied opening docker socket" in reason


def test_network_skip_reason_identifies_endpoint_stage() -> None:
    reasons = network_skip_reasons(
        endpoints=(("upstream chart repository", "https://example.test/index.yaml"),),
        open_url=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
    )

    assert reasons == (
        "network check: upstream chart repository: "
        "https://example.test/index.yaml is not reachable: offline",
    )


def test_e2e_skip_message_lists_all_prerequisite_reasons() -> None:
    assert format_e2e_skip(("helm missing", "registry unavailable")) == (
        "E2E prerequisites unavailable:\n- helm missing\n- registry unavailable"
    )


def test_local_registry_helpers_target_localhost_5000() -> None:
    assert registry_api_url() == f"http://{LOCAL_REGISTRY}/v2/"
    assert is_localhost_5000_oci_ref("oci://localhost:5000/helm/kyverno") is True
    assert is_localhost_5000_oci_ref("oci://registry.example.test/helm/kyverno") is False


def test_k3d_registry_config_routes_localhost_registry_to_host_gateway() -> None:
    assert K3S_IMAGE == "rancher/k3s:v1.35.5-k3s1"
    assert registry_port("localhost:5000") == "5000"
    assert registry_port("registry.example.test") == "5000"
    assert k3d_registry_config("localhost:5000") == (
        "mirrors:\n"
        '  "localhost:5000":\n'
        "    endpoint:\n"
        '      - "http://host.k3d.internal:5000"\n'
    )


def test_cleanup_tolerates_already_missing_release_and_namespace() -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stderr="not found")

    cleanup_helm_release_and_namespace(
        "chartpatch-kyverno-e2e",
        "chartpatch-kyverno",
        run=fake_run,
    )

    assert calls == [
        [
            "helm",
            "uninstall",
            "chartpatch-kyverno",
            "--namespace",
            "chartpatch-kyverno-e2e",
            "--ignore-not-found",
        ],
        [
            "kubectl",
            "delete",
            "namespace",
            "chartpatch-kyverno-e2e",
            "--ignore-not-found=true",
        ],
    ]


def test_pytest_default_selection_excludes_e2e_marker() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["pytest"]["ini_options"]["addopts"] == ["-m", "not e2e"]


def test_oci_chart_ref_candidates_include_helm_push_destination_and_chart_path() -> None:
    assert oci_chart_ref_candidates("oci://localhost:5000/helm/kyverno", "kyverno") == (
        "oci://localhost:5000/helm/kyverno",
        "oci://localhost:5000/helm/kyverno/kyverno",
    )
    assert oci_chart_ref_candidates("oci://localhost:5000/helm/", "kyverno") == (
        "oci://localhost:5000/helm",
        "oci://localhost:5000/helm/kyverno",
    )


def test_pod_container_images_extracts_all_pod_container_sections() -> None:
    pods_json = """
{
  "items": [
    {
      "spec": {
        "initContainers": [{"image": "localhost:5000/init:1"}],
        "containers": [{"image": "localhost:5000/app:1"}],
        "ephemeralContainers": [{"image": "localhost:5000/debug:1"}]
      }
    },
    {
      "spec": {
        "containers": [{"image": "localhost:5000/app:1"}]
      }
    }
  ]
}
"""

    assert pod_container_images(pods_json) == (
        "localhost:5000/app:1",
        "localhost:5000/debug:1",
        "localhost:5000/init:1",
    )


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None
