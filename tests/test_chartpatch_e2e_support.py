from __future__ import annotations

from tests.e2e_support import (
    E2E_ENV_VAR,
    LOCAL_REGISTRY,
    e2e_enabled,
    first_available_runtime,
    is_localhost_5000_oci_ref,
    missing_required_tools,
    registry_api_url,
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
