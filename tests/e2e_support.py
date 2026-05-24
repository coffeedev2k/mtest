from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
import shutil
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen


E2E_ENV_VAR = "CHARTPATCH_RUN_E2E"
LOCAL_REGISTRY = "localhost:5000"
REGISTRY_CONTAINER_NAME = "chartpatch-e2e-registry"
REGISTRY_IMAGE = "registry:2"
REQUIRED_E2E_TOOLS = ("helm", "git", "skopeo")
CONTAINER_RUNTIMES = ("docker", "podman", "nerdctl")


@dataclass(frozen=True)
class RegistryHandle:
    url: str
    started: bool
    runtime: str | None = None
    container_name: str | None = None


class RegistryUnavailable(RuntimeError):
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
