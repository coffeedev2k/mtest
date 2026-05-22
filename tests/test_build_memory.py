from __future__ import annotations

from pathlib import Path

from agent_factory.runtime import _append_completed_task, _initialize_build_memory


def test_initialize_build_memory_creates_readable_ledger(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    feature.write_text("# Feature\n", encoding="utf-8")

    memory = _initialize_build_memory(tmp_path, feature)

    assert memory == tmp_path / "build-memory.md"
    text = memory.read_text(encoding="utf-8")
    assert "# Build Memory" in text
    assert "_No completed tasks yet._" in text


def test_append_completed_task_updates_ledger(tmp_path: Path) -> None:
    feature = tmp_path / "feature.md"
    task = tmp_path / "task.md"
    run_dir = tmp_path / "runs" / "001"
    feature.write_text("# Feature\n", encoding="utf-8")
    task.write_text("# Task 001: Do Thing\n", encoding="utf-8")
    run_dir.mkdir(parents=True)
    memory = _initialize_build_memory(tmp_path, feature)

    class Execution:
        pass

    execution = Execution()
    execution.run_dir = run_dir

    _append_completed_task(memory, 1, task, execution, "abc123")

    text = memory.read_text(encoding="utf-8")
    assert "_No completed tasks yet._" not in text
    assert "Task cycle 1: Task 001: Do Thing" in text
    assert "commit: abc123" in text
