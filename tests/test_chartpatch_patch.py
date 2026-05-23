from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from chartpatch.patch import PatchApplicationError, apply_patch_file
from chartpatch.runner import CommandResult


class RecordingRunner:
    def __init__(
        self,
        *,
        git_am_result: CommandResult | None = None,
        create_reject: bool = False,
        create_rebase_apply: bool = False,
    ) -> None:
        self.git_am_result = git_am_result
        self.create_reject = create_reject
        self.create_rebase_apply = create_rebase_apply
        self.calls: list[tuple[str, ...]] = []
        self.cwd_by_call: list[Path | None] = []

    def run(self, args: Sequence[str], *, cwd: Path | None = None) -> CommandResult:
        call = tuple(str(arg) for arg in args)
        self.calls.append(call)
        self.cwd_by_call.append(cwd)

        if call == ("git", "init") and cwd is not None:
            (cwd / ".git").mkdir()

        if call[:3] == ("git", "am", "--reject"):
            if cwd is not None and self.create_reject:
                (cwd / "templates").mkdir(exist_ok=True)
                (cwd / "templates" / "deployment.yaml.rej").write_text(
                    "rejected hunk\n",
                    encoding="utf-8",
                )
            if cwd is not None and self.create_rebase_apply:
                (cwd / ".git" / "rebase-apply").mkdir(parents=True, exist_ok=True)
            if self.git_am_result is not None:
                return self.git_am_result

        return CommandResult(call, 0, "", "")


def test_apply_patch_initializes_commits_and_applies_patch(tmp_path: Path) -> None:
    chart_dir = _write_chart(tmp_path)
    patch_file = tmp_path / "patches" / "chart.patch"
    patch_file.parent.mkdir()
    patch_file.write_text("format patch\n", encoding="utf-8")
    runner = RecordingRunner()

    result = apply_patch_file(chart_dir, patch_file, runner)

    assert result.chart_dir == chart_dir
    assert result.patch_file == patch_file
    assert (chart_dir / ".git").is_dir()
    assert runner.calls == [
        ("git", "init"),
        ("git", "config", "user.name", "ChartPatch"),
        ("git", "config", "user.email", "chartpatch@example.invalid"),
        ("git", "add", "--all"),
        ("git", "commit", "-m", "Baseline upstream chart"),
        ("git", "am", "--reject", str(patch_file)),
    ]
    assert runner.cwd_by_call == [chart_dir] * 6


def test_apply_patch_reports_command_results_to_callback(tmp_path: Path) -> None:
    chart_dir = _write_chart(tmp_path)
    patch_file = tmp_path / "chart.patch"
    patch_file.write_text("format patch\n", encoding="utf-8")
    runner = RecordingRunner()
    callback_results: list[tuple[str, tuple[str, ...]]] = []

    apply_patch_file(
        chart_dir,
        patch_file,
        runner,
        on_result=lambda label, result: callback_results.append((label, result.args)),
    )

    assert callback_results == [
        ("git-init", ("git", "init")),
        ("git-config-user-name", ("git", "config", "user.name", "ChartPatch")),
        (
            "git-config-user-email",
            ("git", "config", "user.email", "chartpatch@example.invalid"),
        ),
        ("git-add", ("git", "add", "--all")),
        ("git-commit-baseline", ("git", "commit", "-m", "Baseline upstream chart")),
        ("git-am", ("git", "am", "--reject", str(patch_file))),
    ]


def test_apply_patch_raises_clear_failure_when_git_am_fails(tmp_path: Path) -> None:
    chart_dir = _write_chart(tmp_path)
    patch_file = tmp_path / "chart.patch"
    patch_file.write_text("format patch\n", encoding="utf-8")
    runner = RecordingRunner(
        git_am_result=CommandResult(
            ("git", "am", "--reject", str(patch_file)),
            128,
            "am stdout\n",
            "am stderr\n",
        )
    )

    with pytest.raises(PatchApplicationError) as exc_info:
        apply_patch_file(chart_dir, patch_file, runner)

    message = str(exc_info.value)
    assert "patch application failed" in message
    assert "git am --reject" in message
    assert "exited with code 128" in message
    assert "am stdout" in message
    assert "am stderr" in message


def test_apply_patch_raises_when_reject_file_remains(tmp_path: Path) -> None:
    chart_dir = _write_chart(tmp_path)
    patch_file = tmp_path / "chart.patch"
    patch_file.write_text("format patch\n", encoding="utf-8")
    runner = RecordingRunner(create_reject=True)

    with pytest.raises(PatchApplicationError) as exc_info:
        apply_patch_file(chart_dir, patch_file, runner)

    message = str(exc_info.value)
    assert "reject files remain" in message
    assert "templates/deployment.yaml.rej" in message


def test_apply_patch_raises_when_rebase_apply_remains(tmp_path: Path) -> None:
    chart_dir = _write_chart(tmp_path)
    patch_file = tmp_path / "chart.patch"
    patch_file.write_text("format patch\n", encoding="utf-8")
    runner = RecordingRunner(create_rebase_apply=True)

    with pytest.raises(PatchApplicationError) as exc_info:
        apply_patch_file(chart_dir, patch_file, runner)

    message = str(exc_info.value)
    assert "unfinished git am state remains" in message
    assert str(chart_dir / ".git" / "rebase-apply") in message


def _write_chart(tmp_path: Path) -> Path:
    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    (chart_dir / "Chart.yaml").write_text(
        "apiVersion: v2\nname: chart\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    return chart_dir
