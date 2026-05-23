from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence


REQUIRED_SYNC_BINARIES = ("helm", "git", "skopeo")


class MissingRuntimeDependencies(RuntimeError):
    """Raised when one or more required sync runtime binaries are unavailable."""

    def __init__(self, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        label = "dependency" if len(self.missing) == 1 else "dependencies"
        names = ", ".join(self.missing)
        super().__init__(f"missing required runtime {label}: {names}")


def check_required_binaries(
    required: Sequence[str] = REQUIRED_SYNC_BINARIES,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> None:
    missing = tuple(binary for binary in required if which(binary) is None)
    if missing:
        raise MissingRuntimeDependencies(missing)
