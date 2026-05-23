from __future__ import annotations

import pytest

from chartpatch.dependencies import (
    REQUIRED_SYNC_BINARIES,
    MissingRuntimeDependencies,
    check_required_binaries,
)


def test_dependency_checker_succeeds_when_all_required_binaries_are_present() -> None:
    checked: list[str] = []

    def fake_which(binary: str) -> str | None:
        checked.append(binary)
        return f"/usr/bin/{binary}"

    check_required_binaries(which=fake_which)

    assert tuple(checked) == REQUIRED_SYNC_BINARIES


@pytest.mark.parametrize(
    ("missing", "message"),
    [
        ({"helm"}, "missing required runtime dependency: helm"),
        ({"git", "skopeo"}, "missing required runtime dependencies: git, skopeo"),
    ],
)
def test_dependency_checker_reports_exact_missing_binaries(
    missing: set[str],
    message: str,
) -> None:
    def fake_which(binary: str) -> str | None:
        if binary in missing:
            return None
        return f"/usr/bin/{binary}"

    with pytest.raises(MissingRuntimeDependencies) as exc_info:
        check_required_binaries(which=fake_which)

    assert exc_info.value.missing == tuple(
        binary for binary in REQUIRED_SYNC_BINARIES if binary in missing
    )
    assert str(exc_info.value) == message
