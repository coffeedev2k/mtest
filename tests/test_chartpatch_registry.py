from __future__ import annotations

from collections.abc import Sequence

import pytest

from chartpatch import registry
from chartpatch.registry import LocalRegistryError, ensure_local_registry
from chartpatch.runner import CommandResult


class RecordingRunner:
    def __init__(self, results: Sequence[CommandResult]) -> None:
        self.results = iter(results)
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str], **kwargs) -> CommandResult:
        self.calls.append(tuple(args))
        return next(self.results)


def result(args: Sequence[str], returncode: int = 0) -> CommandResult:
    return CommandResult(tuple(args), returncode, "", "")


def test_reuses_reachable_registry_without_docker(monkeypatch) -> None:
    runner = RecordingRunner(())
    monkeypatch.setattr(registry, "_registry_is_ready", lambda url, **kwargs: True)

    local = ensure_local_registry("localhost:5000", runner=runner)

    assert local.api_url == "http://localhost:5000/v2/"
    assert local.started is False
    assert runner.calls == []


def test_starts_existing_registry_container(monkeypatch) -> None:
    readiness = iter((False, True))
    monkeypatch.setattr(
        registry,
        "_registry_is_ready",
        lambda url, **kwargs: next(readiness),
    )
    runner = RecordingRunner(
        (
            result(("docker", "inspect", "chartpatch-registry")),
            result(("docker", "start", "chartpatch-registry")),
        )
    )

    local = ensure_local_registry("localhost:5000", runner=runner)

    assert local.started is True
    assert runner.calls == [
        ("docker", "inspect", "chartpatch-registry"),
        ("docker", "start", "chartpatch-registry"),
    ]


def test_runs_new_registry_container_on_configured_port(monkeypatch) -> None:
    readiness = iter((False, True))
    monkeypatch.setattr(
        registry,
        "_registry_is_ready",
        lambda url, **kwargs: next(readiness),
    )
    runner = RecordingRunner(
        (
            result(("docker", "inspect", "custom-registry"), returncode=1),
            result(("docker", "run")),
        )
    )

    local = ensure_local_registry(
        "127.0.0.1:5500",
        container_name="custom-registry",
        image="registry:2.8",
        runner=runner,
    )

    assert local.started is True
    assert runner.calls[1] == (
        "docker",
        "run",
        "-d",
        "--restart",
        "unless-stopped",
        "-p",
        "5500:5000",
        "--name",
        "custom-registry",
        "-e",
        "REGISTRY_STORAGE_DELETE_ENABLED=true",
        "registry:2.8",
    )


@pytest.mark.parametrize(
    "address",
    (
        "registry.example.com:5000",
        "localhost",
        "http://localhost:5000",
        "localhost:not-a-port",
        "localhost:70000",
    ),
)
def test_rejects_non_local_or_invalid_registry_addresses(address: str) -> None:
    with pytest.raises(LocalRegistryError):
        ensure_local_registry(address)


def test_authenticated_registry_generates_htpasswd_and_mounts_it(
    tmp_path,
    monkeypatch,
) -> None:
    readiness = iter((False, True))
    monkeypatch.setattr(
        registry,
        "_registry_is_ready",
        lambda url, **kwargs: next(readiness),
    )
    runner = RecordingRunner(
        (
            result(("docker", "rm", "-f", "secured")),
            CommandResult(
                ("docker", "run", "htpasswd"),
                0,
                "chartpatch:$2y$05$hash\n",
                "",
            ),
            result(("docker", "run")),
        )
    )

    local = ensure_local_registry(
        "localhost:5000",
        container_name="secured",
        username="chartpatch",
        password="secret-password",
        auth_dir=tmp_path,
        runner=runner,
    )

    assert local.started is True
    assert (tmp_path / "htpasswd").read_text(encoding="utf-8").startswith(
        "chartpatch:$2y$"
    )
    assert "secret-password" not in " ".join(runner.calls[1])
    assert "REGISTRY_AUTH=htpasswd" in runner.calls[2]
    assert f"{tmp_path}:/auth:ro" in runner.calls[2]
