from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
import shutil
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


E2E_ENV_VAR = "CHARTPATCH_RUN_E2E"
LOCAL_REGISTRY = "localhost:5000"
REGISTRY_CONTAINER_NAME = "chartpatch-e2e-registry"
REGISTRY_IMAGE = "registry:2"
K3D_CLUSTER_NAME = "chartpatch-e2e"
REQUIRED_E2E_TOOLS = ("helm", "git", "skopeo", "kubectl", "k3d")
CONTAINER_RUNTIMES = ("docker", "podman", "nerdctl")


@dataclass(frozen=True)
class RegistryHandle:
    url: str
    started: bool
    runtime: str | None = None
    container_name: str | None = None


class RegistryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ClusterHandle:
    name: str
    started: bool


class ClusterUnavailable(RuntimeError):
    pass


def e2e_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    return environ.get(E2E_ENV_VAR) == "1"


def missing_required_tools(
    *,
    required: Sequence[str] = REQUIRED_E2E_TOOLS,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, ...]:
    return tuple(tool for tool in required if which(tool) is None)


def first_available_runtime(
    *,
    runtimes: Sequence[str] = CONTAINER_RUNTIMES,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    return next((runtime for runtime in runtimes if which(runtime) is not None), None)


def registry_api_url(registry: str = LOCAL_REGISTRY) -> str:
    return f"http://{registry.rstrip('/')}/v2/"


def is_localhost_5000_oci_ref(chart_ref: str) -> bool:
    return chart_ref.startswith(f"oci://{LOCAL_REGISTRY}/")


def registry_is_reachable(registry: str = LOCAL_REGISTRY, *, timeout: float = 1.0) -> bool:
    try:
        with urlopen(registry_api_url(registry), timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, URLError):
        return False


def ensure_local_registry(
    *,
    registry: str = LOCAL_REGISTRY,
    runtime: str | None = None,
    timeout_seconds: float = 30.0,
) -> RegistryHandle:
    if registry_is_reachable(registry):
        return RegistryHandle(url=registry, started=False)

    selected_runtime = runtime or first_available_runtime()
    if selected_runtime is None:
        raise RegistryUnavailable(
            f"{registry} is not reachable and no compatible container runtime was found"
        )

    command = [
        selected_runtime,
        "run",
        "-d",
        "--rm",
        "-p",
        "5000:5000",
        "--name",
        REGISTRY_CONTAINER_NAME,
        REGISTRY_IMAGE,
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RegistryUnavailable(
            "failed to start local registry with "
            f"{selected_runtime}: {completed.stderr.strip() or completed.stdout.strip()}"
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if registry_is_reachable(registry):
            return RegistryHandle(
                url=registry,
                started=True,
                runtime=selected_runtime,
                container_name=REGISTRY_CONTAINER_NAME,
            )
        time.sleep(0.5)

    subprocess.run(
        [selected_runtime, "stop", REGISTRY_CONTAINER_NAME],
        text=True,
        capture_output=True,
        check=False,
    )
    raise RegistryUnavailable(f"local registry at {registry} did not become reachable")


def stop_local_registry(handle: RegistryHandle) -> None:
    if not handle.started or handle.runtime is None or handle.container_name is None:
        return
    subprocess.run(
        [handle.runtime, "stop", handle.container_name],
        text=True,
        capture_output=True,
        check=False,
    )


def k3d_registry_config(registry: str = LOCAL_REGISTRY) -> str:
    return (
        "mirrors:\n"
        f'  "{registry}":\n'
        "    endpoint:\n"
        f'      - "http://host.k3d.internal:{registry_port(registry)}"\n'
    )


def registry_port(registry: str) -> str:
    if ":" not in registry:
        return "5000"
    return registry.rsplit(":", 1)[1]


def k3d_cluster_exists(name: str = K3D_CLUSTER_NAME) -> bool:
    completed = subprocess.run(
        ["k3d", "cluster", "list", "-o", "json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ClusterUnavailable(
            "failed to list k3d clusters: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    try:
        clusters = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise ClusterUnavailable(f"failed to parse k3d cluster list JSON: {exc}") from None
    return any(cluster.get("name") == name for cluster in clusters)


def ensure_k3d_cluster(
    *,
    name: str = K3D_CLUSTER_NAME,
    registry: str = LOCAL_REGISTRY,
    timeout_seconds: int = 180,
) -> ClusterHandle:
    if k3d_cluster_exists(name):
        _switch_k3d_context(name)
        return ClusterHandle(name=name, started=False)

    with tempfile.TemporaryDirectory(prefix="chartpatch-k3d-") as temp_dir:
        registry_config = os.path.join(temp_dir, "registries.yaml")
        with open(registry_config, "w", encoding="utf-8") as file:
            file.write(k3d_registry_config(registry))

        completed = subprocess.run(
            [
                "k3d",
                "cluster",
                "create",
                name,
                "--registry-config",
                registry_config,
                "--wait",
                "--timeout",
                f"{timeout_seconds}s",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0:
        raise ClusterUnavailable(
            "failed to create k3d cluster: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )

    _switch_k3d_context(name)
    return ClusterHandle(name=name, started=True)


def delete_k3d_cluster(handle: ClusterHandle) -> None:
    if not handle.started:
        return
    subprocess.run(
        ["k3d", "cluster", "delete", handle.name],
        text=True,
        capture_output=True,
        check=False,
    )


def _switch_k3d_context(name: str) -> None:
    completed = subprocess.run(
        ["k3d", "kubeconfig", "merge", name, "--kubeconfig-switch-context"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ClusterUnavailable(
            "failed to switch kubectl context to k3d cluster: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )


def oci_chart_ref_candidates(chart_ref: str, chart_name: str) -> tuple[str, ...]:
    base = chart_ref.rstrip("/")
    appended = f"{base}/{chart_name}"
    if appended == base:
        return (base,)
    return (base, appended)


def pod_container_images(pods_json: str) -> tuple[str, ...]:
    data = json.loads(pods_json)
    images: set[str] = set()
    for pod in data.get("items", []):
        spec = pod.get("spec", {})
        for field in ("initContainers", "containers", "ephemeralContainers"):
            for container in spec.get(field, []):
                image = container.get("image")
                if image:
                    images.add(image)
    return tuple(sorted(images))
