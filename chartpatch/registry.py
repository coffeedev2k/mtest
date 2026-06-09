from __future__ import annotations

from dataclasses import dataclass
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .runner import CommandResult, CommandRunner


DEFAULT_REGISTRY_CONTAINER = "chartpatch-registry"
DEFAULT_REGISTRY_IMAGE = "registry:2"
DEFAULT_REGISTRY_TIMEOUT_SECONDS = 30.0


class LocalRegistryError(RuntimeError):
    """Raised when quickrun cannot provide the configured local registry."""


@dataclass(frozen=True)
class LocalRegistry:
    address: str
    api_url: str
    container_name: str
    started: bool


def ensure_local_registry(
    address: str,
    *,
    container_name: str = DEFAULT_REGISTRY_CONTAINER,
    image: str = DEFAULT_REGISTRY_IMAGE,
    timeout_seconds: float = DEFAULT_REGISTRY_TIMEOUT_SECONDS,
    runner: CommandRunner | None = None,
) -> LocalRegistry:
    host, port = _parse_local_registry_address(address)
    api_url = f"http://{host}:{port}/v2/"
    if _registry_is_ready(api_url):
        return LocalRegistry(
            address=address,
            api_url=api_url,
            container_name=container_name,
            started=False,
        )

    command_runner = runner or CommandRunner()
    inspect = command_runner.run(["docker", "inspect", container_name])
    if inspect.returncode == 0:
        result = command_runner.run(["docker", "start", container_name])
        action = "start"
    else:
        result = command_runner.run(
            [
                "docker",
                "run",
                "-d",
                "--restart",
                "unless-stopped",
                "-p",
                f"{port}:5000",
                "--name",
                container_name,
                "-e",
                "REGISTRY_STORAGE_DELETE_ENABLED=true",
                image,
            ]
        )
        action = "run"

    if result.returncode != 0:
        raise LocalRegistryError(
            f"docker {action} failed for {container_name}: {_command_error(result)}"
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _registry_is_ready(api_url):
            return LocalRegistry(
                address=address,
                api_url=api_url,
                container_name=container_name,
                started=True,
            )
        time.sleep(0.25)

    raise LocalRegistryError(
        f"local registry {address} did not become ready within "
        f"{timeout_seconds:g} seconds"
    )


def _parse_local_registry_address(address: str) -> tuple[str, int]:
    value = address.strip()
    if not value:
        raise LocalRegistryError("registry.url must not be empty")
    if "://" in value or "/" in value:
        raise LocalRegistryError(
            "quickrun registry.url must be a local host and port, "
            "for example localhost:5000"
        )

    host, separator, port_text = value.rpartition(":")
    if not separator or not host or not port_text:
        raise LocalRegistryError(
            "quickrun registry.url must include a port, "
            "for example localhost:5000"
        )
    if host not in {"localhost", "127.0.0.1"}:
        raise LocalRegistryError(
            "quickrun can only start a registry on localhost or 127.0.0.1"
        )
    try:
        port = int(port_text)
    except ValueError:
        raise LocalRegistryError(
            f"quickrun registry.url has an invalid port: {port_text}"
        ) from None
    if not 1 <= port <= 65535:
        raise LocalRegistryError(
            f"quickrun registry.url port must be between 1 and 65535: {port}"
        )
    return host, port


def _registry_is_ready(api_url: str) -> bool:
    try:
        with urlopen(api_url, timeout=1.0) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def _command_error(result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip()
    if detail:
        return detail
    return f"exit code {result.returncode}"
