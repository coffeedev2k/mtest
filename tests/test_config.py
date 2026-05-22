from __future__ import annotations

from pathlib import Path

import pytest

from agent_factory.config import ConfigError, load_factory_config


def test_valid_factory_config_parses() -> None:
    config = load_factory_config(Path("factory.yaml"))

    assert config.name == "local-agent-factory"
    assert config.run_root == Path("runs")
    assert config.runtime == "python_workers"
    assert config.backend == "codex_exec"
    assert [agent.name for agent in config.agents] == [
        "planner",
        "architect",
        "task_generator",
        "implementer",
        "reviewer",
        "tester",
    ]


def test_missing_factory_name_fails(tmp_path: Path) -> None:
    path = tmp_path / "factory.yaml"
    path.write_text(
        """
factory:
  run_root: runs
  runtime: python_workers
  backend: codex_exec
backend:
  codex_exec:
    command: codex
    args: []
agents: {}
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="factory.name is required"):
        load_factory_config(path)


def test_agent_concurrency_must_be_positive(tmp_path: Path) -> None:
    path = tmp_path / "factory.yaml"
    path.write_text(
        """
factory:
  name: test
  run_root: runs
  runtime: python_workers
  backend: codex_exec
backend:
  codex_exec:
    command: codex
    args: []
agents:
  implementer:
    worker_module: agent_factory.worker
    prompt: agents/implementer.md
    concurrency: 0
    outputs: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="agents.implementer.concurrency must be >= 1"):
        load_factory_config(path)
