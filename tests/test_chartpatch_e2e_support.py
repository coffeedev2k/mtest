from __future__ import annotations

from tests.e2e_support import (
    E2E_ENV_VAR,
    LOCAL_REGISTRY,
    e2e_enabled,
    first_available_runtime,
    is_localhost_5000_oci_ref,
    k3d_registry_config,
    missing_required_tools,
    oci_chart_ref_candidates,
    pod_container_images,
    registry_api_url,
    registry_port,
)


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


def test_first_available_runtime_preserves_preference_order() -> None:
    available = {"podman": "/usr/bin/podman", "nerdctl": "/usr/bin/nerdctl"}

    assert first_available_runtime(
        runtimes=("docker", "podman", "nerdctl"),
        which=available.get,
    ) == "podman"


def test_local_registry_helpers_target_localhost_5000() -> None:
    assert registry_api_url() == f"http://{LOCAL_REGISTRY}/v2/"
    assert is_localhost_5000_oci_ref("oci://localhost:5000/helm/kyverno") is True
    assert is_localhost_5000_oci_ref("oci://registry.example.test/helm/kyverno") is False


def test_k3d_registry_config_routes_localhost_registry_to_host_gateway() -> None:
    assert registry_port("localhost:5000") == "5000"
    assert registry_port("registry.example.test") == "5000"
    assert k3d_registry_config("localhost:5000") == (
        "mirrors:\n"
        '  "localhost:5000":\n'
        "    endpoint:\n"
        '      - "http://host.k3d.internal:5000"\n'
    )


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
