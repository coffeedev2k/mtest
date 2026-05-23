from __future__ import annotations

from pathlib import Path

from agent_factory.runtime import _extract_write_scope


def test_extract_write_scope_reads_markdown_list(tmp_path: Path) -> None:
    task = tmp_path / "task.md"
    task.write_text(
        "# Task\n\n## Write Scope\n\n- `src/a.py`\n- tests/test_a.py\n\n## Acceptance Criteria\n\nDone.\n",
        encoding="utf-8",
    )

    assert _extract_write_scope(task) == ["src/a.py", "tests/test_a.py"]
