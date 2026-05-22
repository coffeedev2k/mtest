from __future__ import annotations

from pathlib import Path

from agent_factory.runtime import _report_passed


def test_report_passed_detects_pass(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("**Pass/Fail Decision**\n\nPass.\n", encoding="utf-8")

    assert _report_passed(report) is True


def test_report_passed_detects_fail(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    report.write_text("**Pass/Fail Decision**\n\nFail.\n", encoding="utf-8")

    assert _report_passed(report) is False
