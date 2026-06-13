from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandRunnerError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        super().__init__(
            f"command failed with exit code {result.returncode}: {' '.join(result.args)}"
        )
        self.result = result


class CommandRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = False,
        input_text: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            input=input_text,
            env=env,
        )
        result = CommandResult(
            args=tuple(str(arg) for arg in args),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if check and result.returncode != 0:
            raise CommandRunnerError(result)
        return result
