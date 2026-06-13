from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .images import ImageTargetMapping
from .runner import CommandResult, CommandRunner


@dataclass(frozen=True)
class MirroredImage:
    source: str
    target: str


class ImageMirrorError(RuntimeError):
    def __init__(self, mapping: ImageTargetMapping, result: CommandResult) -> None:
        self.mapping = mapping
        self.result = result
        super().__init__(_format_image_mirror_failure(mapping, result))


MirrorResultCallback = Callable[[int, ImageTargetMapping, CommandResult], None]


def mirror_image_mappings(
    mappings: Sequence[ImageTargetMapping],
    runner: CommandRunner,
    *,
    on_result: MirrorResultCallback | None = None,
) -> tuple[MirroredImage, ...]:
    mirrored: list[MirroredImage] = []
    for index, mapping in enumerate(mappings, start=1):
        result = runner.run(_skopeo_copy_args(mapping))
        if on_result is not None:
            on_result(index, mapping, result)
        if result.returncode != 0:
            raise ImageMirrorError(mapping, result)
        mirrored.append(MirroredImage(source=mapping.source, target=mapping.target))
    return tuple(mirrored)


def _skopeo_copy_args(mapping: ImageTargetMapping) -> list[str]:
    return [
        "skopeo",
        "copy",
        "--dest-tls-verify=false",
        f"docker://{mapping.source}",
        f"docker://{mapping.target}",
    ]


def _format_image_mirror_failure(
    mapping: ImageTargetMapping,
    result: CommandResult,
) -> str:
    lines = [
        "image mirror failed",
        f"source image: {mapping.source}",
        f"target image: {mapping.target}",
        f"command: {' '.join(result.args)}",
        f"exit status: {result.returncode}",
    ]
    if result.stdout.strip():
        lines.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr.strip():
        lines.append(f"stderr:\n{result.stderr.rstrip()}")
    return "\n".join(lines)
