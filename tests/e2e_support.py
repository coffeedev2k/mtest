from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


E2E_ENV_VAR = "CHARTPATCH_RUN_E2E"
LOCAL_REGISTRY = "localhost:5000"
REGISTRY_CONTAINER_NAME = "chartpatch-e2e-registry"
REGISTRY_IMAGE = "registry:2"
REGISTRY_HTPASSWD_IMAGE = "httpd:2.4-alpine"
REGISTRY_USERNAME = "chartpatch"
REGISTRY_PASSWORD = "chartpatch-e2e-password"
K3D_CLUSTER_NAME = "chartpatch-e2e"
K3S_IMAGE = "rancher/k3s:v1.35.5-k3s1"
K3S_DISABLE_TRAEFIK_ARG = "--disable=traefik@server:0"
REQUIRED_E2E_TOOLS = ("helm", "git", "skopeo", "kubectl", "k3d")
CONTAINER_RUNTIMES = ("docker", "podman", "nerdctl")
REQUIRED_NETWORK_ENDPOINTS = (
    ("upstream chart repository", "https://kyverno.github.io/kyverno/index.yaml"),
    ("upstream Kyverno image registry", "https://ghcr.io/v2/"),
    ("test workload image registry", "https://registry.k8s.io/v2/"),
)


@dataclass(frozen=True)
class RegistryHandle:
    url: str
    started: bool
    runtime: str | None = None
    container_name: str | None = None
    auth_dir: str | None = None


class RegistryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ClusterHandle:
    name: str
    started: bool


class ClusterUnavailable(RuntimeError):
    pass


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
OpenUrl = Callable[..., object]


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


def executable_display_name(executable: str) -> str:
    if executable == "k3d":
        return "local k3s cluster manager (k3d)"
    return executable


def format_skip_reason(stage: str, dependency: str, detail: str) -> str:
    return f"{stage}: {dependency}: {detail}"


def missing_executable_skip_reasons(
    *,
    required: Sequence[str] = REQUIRED_E2E_TOOLS,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, ...]:
    return tuple(
        format_skip_reason(
            "executable check",
            executable_display_name(tool),
            "executable not found on PATH",
        )
        for tool in missing_required_tools(required=required, which=which)
    )


def _command_failure_detail(
    command: Sequence[str],
    *,
    run: RunCommand = subprocess.run,
    timeout_seconds: float = 15.0,
) -> str | None:
    try:
        completed = run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return "executable not found on PATH"
    except PermissionError as exc:
        return f"permission denied while running command: {exc}"
    except subprocess.TimeoutExpired:
        return f"command timed out after {timeout_seconds:g}s"

    if completed.returncode == 0:
        return None
    output = completed.stderr.strip() or completed.stdout.strip()
    if output:
        return output
    return f"command exited with status {completed.returncode}"


def container_runtime_skip_reason(
    *,
    runtimes: Sequence[str] = CONTAINER_RUNTIMES,
    which: Callable[[str], str | None] = shutil.which,
    run: RunCommand = subprocess.run,
) -> str | None:
    runtime = first_available_runtime(runtimes=runtimes, which=which)
    if runtime is None:
        return format_skip_reason(
            "container runtime check",
            "Docker-compatible runtime",
            f"none found on PATH ({', '.join(runtimes)})",
        )

    detail = _command_failure_detail([runtime, "info"], run=run)
    if detail is None:
        return None
    return format_skip_reason(
        "container runtime check",
        runtime,
        f"runtime is not usable; check daemon/socket access and permissions: {detail}",
    )


def local_k3s_skip_reason(*, run: RunCommand = subprocess.run) -> str | None:
    detail = _command_failure_detail(["k3d", "cluster", "list", "-o", "json"], run=run)
    if detail is None:
        return None
    return format_skip_reason(
        "local k3s cluster check",
        "k3d",
        f"cannot list local k3s clusters; check runtime permissions: {detail}",
    )


def network_skip_reasons(
    *,
    endpoints: Sequence[tuple[str, str]] = REQUIRED_NETWORK_ENDPOINTS,
    open_url: OpenUrl = urlopen,
    timeout: float = 3.0,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for dependency, endpoint in endpoints:
        try:
            with open_url(endpoint, timeout=timeout) as response:
                status = getattr(response, "status", 0)
                if status >= 500:
                    reasons.append(
                        format_skip_reason(
                            "network check",
                            dependency,
                            f"{endpoint} returned HTTP {status}",
                        )
                    )
        except HTTPError as exc:
            if exc.code >= 500:
                reasons.append(
                    format_skip_reason(
                        "network check",
                        dependency,
                        f"{endpoint} returned HTTP {exc.code}",
                    )
                )
        except (OSError, URLError) as exc:
            reasons.append(
                format_skip_reason(
                    "network check",
                    dependency,
                    f"{endpoint} is not reachable: {exc}",
                )
            )
    return tuple(reasons)


def collect_e2e_prerequisite_skip_reasons(
    *,
    required: Sequence[str] = REQUIRED_E2E_TOOLS,
    runtimes: Sequence[str] = CONTAINER_RUNTIMES,
    which: Callable[[str], str | None] = shutil.which,
    run: RunCommand = subprocess.run,
    open_url: OpenUrl = urlopen,
) -> tuple[str, ...]:
    reasons = list(missing_executable_skip_reasons(required=required, which=which))
    runtime_reason = container_runtime_skip_reason(
        runtimes=runtimes,
        which=which,
        run=run,
    )
    if runtime_reason is not None:
        reasons.append(runtime_reason)
    if which("k3d") is not None:
        k3s_reason = local_k3s_skip_reason(run=run)
        if k3s_reason is not None:
            reasons.append(k3s_reason)
    reasons.extend(network_skip_reasons(open_url=open_url))
    return tuple(reasons)


def format_e2e_skip(reasons: Sequence[str]) -> str:
    return "E2E prerequisites unavailable:\n- " + "\n- ".join(reasons)


def registry_api_url(registry: str = LOCAL_REGISTRY) -> str:
    return f"http://{registry.rstrip('/')}/v2/"


def is_localhost_5000_oci_ref(chart_ref: str) -> bool:
    return chart_ref.startswith(f"oci://{LOCAL_REGISTRY}/")


def registry_is_reachable(
    registry: str = LOCAL_REGISTRY,
    *,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 1.0,
) -> bool:
    request = Request(registry_api_url(registry))
    if username is not None and password is not None:
        token = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("ascii")
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (OSError, URLError):
        return False


def ensure_local_registry(
    *,
    registry: str = LOCAL_REGISTRY,
    username: str = REGISTRY_USERNAME,
    password: str = REGISTRY_PASSWORD,
    runtime: str | None = None,
    timeout_seconds: float = 30.0,
) -> RegistryHandle:
    if registry_is_reachable(
        registry,
        username=username,
        password=password,
    ):
        return RegistryHandle(url=registry, started=False)

    selected_runtime = runtime or first_available_runtime()
    if selected_runtime is None:
        raise RegistryUnavailable(
            f"{registry} is not reachable and no compatible container runtime was found"
        )

    auth_dir = tempfile.mkdtemp(prefix="chartpatch-registry-auth-")
    htpasswd = subprocess.run(
        [
            selected_runtime,
            "run",
            "--rm",
            "-i",
            REGISTRY_HTPASSWD_IMAGE,
            "htpasswd",
            "-Bni",
            username,
        ],
        input=f"{password}\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if htpasswd.returncode != 0 or not htpasswd.stdout.strip():
        shutil.rmtree(auth_dir, ignore_errors=True)
        raise RegistryUnavailable(
            "local registry: failed to generate htpasswd entry: "
            f"{htpasswd.stderr.strip() or htpasswd.stdout.strip()}"
        )
    auth_file = os.path.join(auth_dir, "htpasswd")
    with open(auth_file, "w", encoding="utf-8") as file:
        file.write(htpasswd.stdout)
    os.chmod(auth_file, 0o600)

    command = [
        selected_runtime,
        "run",
        "-d",
        "--rm",
        "-p",
        "5000:5000",
        "--name",
        REGISTRY_CONTAINER_NAME,
        "-e",
        "REGISTRY_AUTH=htpasswd",
        "-e",
        "REGISTRY_AUTH_HTPASSWD_REALM=ChartPatch E2E Registry",
        "-e",
        "REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd",
        "-v",
        f"{auth_dir}:/auth:ro",
        REGISTRY_IMAGE,
    ]
    subprocess.run(
        [selected_runtime, "rm", "-f", REGISTRY_CONTAINER_NAME],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
    except PermissionError as exc:
        raise RegistryUnavailable(
            f"local registry: permission denied starting registry with {selected_runtime}: {exc}"
        ) from None
    except FileNotFoundError:
        raise RegistryUnavailable(
            f"local registry: container runtime {selected_runtime} was not found"
        ) from None
    if completed.returncode != 0:
        raise RegistryUnavailable(
            "local registry: failed to start registry with "
            f"{selected_runtime}: {completed.stderr.strip() or completed.stdout.strip()}"
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if registry_is_reachable(
            registry,
            username=username,
            password=password,
        ):
            return RegistryHandle(
                url=registry,
                started=True,
                runtime=selected_runtime,
                container_name=REGISTRY_CONTAINER_NAME,
                auth_dir=auth_dir,
            )
        time.sleep(0.5)

    subprocess.run(
        [selected_runtime, "stop", REGISTRY_CONTAINER_NAME],
        text=True,
        capture_output=True,
        check=False,
    )
    shutil.rmtree(auth_dir, ignore_errors=True)
    raise RegistryUnavailable(f"local registry: {registry} did not become reachable")


def stop_local_registry(handle: RegistryHandle) -> None:
    if not handle.started or handle.runtime is None or handle.container_name is None:
        return
    subprocess.run(
        [handle.runtime, "stop", handle.container_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if handle.auth_dir is not None:
        shutil.rmtree(handle.auth_dir, ignore_errors=True)


def k3d_registry_config(
    registry: str = LOCAL_REGISTRY,
    *,
    username: str = REGISTRY_USERNAME,
    password: str = REGISTRY_PASSWORD,
) -> str:
    mirror = f"host.k3d.internal:{registry_port(registry)}"
    return (
        "mirrors:\n"
        f'  "{registry}":\n'
        "    endpoint:\n"
        f'      - "http://{mirror}"\n'
        "configs:\n"
        f'  "{registry}":\n'
        "    auth:\n"
        f'      username: "{username}"\n'
        f'      password: "{password}"\n'
        f'  "{mirror}":\n'
        "    auth:\n"
        f'      username: "{username}"\n'
        f'      password: "{password}"\n'
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
    username: str = REGISTRY_USERNAME,
    password: str = REGISTRY_PASSWORD,
    timeout_seconds: int = 180,
) -> ClusterHandle:
    if k3d_cluster_exists(name):
        completed = subprocess.run(
            ["k3d", "cluster", "start", name, "--wait"],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ClusterUnavailable(
                "failed to start existing k3d cluster: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        _switch_k3d_context(name)
        return ClusterHandle(name=name, started=False)

    with tempfile.TemporaryDirectory(prefix="chartpatch-k3d-") as temp_dir:
        registry_config = os.path.join(temp_dir, "registries.yaml")
        with open(registry_config, "w", encoding="utf-8") as file:
            file.write(
                k3d_registry_config(
                    registry,
                    username=username,
                    password=password,
                )
            )

        completed = subprocess.run(
            [
                "k3d",
                "cluster",
                "create",
                name,
                "--image",
                K3S_IMAGE,
                "--no-lb",
                "--k3s-arg",
                K3S_DISABLE_TRAEFIK_ARG,
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


def cleanup_helm_release_and_namespace(
    namespace: str,
    release: str,
    *,
    run: RunCommand = subprocess.run,
) -> None:
    run(
        ["helm", "uninstall", release, "--namespace", namespace, "--ignore-not-found"],
        text=True,
        capture_output=True,
        check=False,
    )
    run(
        ["kubectl", "delete", "namespace", namespace, "--ignore-not-found=true"],
        text=True,
        capture_output=True,
        check=False,
    )


def _switch_k3d_context(name: str) -> None:
    completed = subprocess.run(
        [
            "k3d",
            "kubeconfig",
            "merge",
            name,
            "--kubeconfig-merge-default",
            "--kubeconfig-switch-context",
        ],
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
