from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when factory config is invalid."""


@dataclass(frozen=True)
class AgentConfig:
    name: str
    worker_module: str
    prompt: str
    concurrency: int
    outputs: tuple[str, ...]


@dataclass(frozen=True)
class FactoryConfig:
    name: str
    run_root: Path
    runtime: str
    backend: str
    require_review: bool
    require_tests: bool
    max_fix_loops: int
    agents: tuple[AgentConfig, ...]


def load_factory_config(path: Path) -> FactoryConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("factory config must be a YAML mapping")

    factory = _required_mapping(raw, "factory")
    agents = _required_mapping(raw, "agents")

    parsed_agents = []
    for name, value in agents.items():
        if not isinstance(value, dict):
            raise ConfigError(f"agents.{name} must be a mapping")
        outputs = value.get("outputs", [])
        if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
            raise ConfigError(f"agents.{name}.outputs must be a list of strings")
        concurrency = int(value.get("concurrency", 1))
        if concurrency < 1:
            raise ConfigError(f"agents.{name}.concurrency must be >= 1")
        parsed_agents.append(
            AgentConfig(
                name=name,
                worker_module=_required_string(value, "worker_module", f"agents.{name}"),
                prompt=_required_string(value, "prompt", f"agents.{name}"),
                concurrency=concurrency,
                outputs=tuple(outputs),
            )
        )

    return FactoryConfig(
        name=_required_string(factory, "name", "factory"),
        run_root=Path(_required_string(factory, "run_root", "factory")),
        runtime=_required_string(factory, "runtime", "factory"),
        backend=_required_string(factory, "backend", "factory"),
        require_review=bool(factory.get("require_review", True)),
        require_tests=bool(factory.get("require_tests", True)),
        max_fix_loops=int(factory.get("max_fix_loops", 3)),
        agents=tuple(parsed_agents),
    )


def _required_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a mapping")
    return value


def _required_string(data: dict[str, Any], key: str, prefix: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{prefix}.{key} is required")
    return value
