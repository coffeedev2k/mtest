from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .images import ImageTargetMapping, canonicalize_digest_reference
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
    destination_auth_file: str | None = None,
    on_result: MirrorResultCallback | None = None,
) -> tuple[MirroredImage, ...]:
    mirrored: list[MirroredImage] = []
    for index, mapping in enumerate(mappings, start=1):
        result = runner.run(
            _skopeo_copy_args(
                mapping,
                destination_auth_file=destination_auth_file,
            )
        )
        if on_result is not None:
            on_result(index, mapping, result)
        if result.returncode != 0:
            raise ImageMirrorError(mapping, result)
        mirrored.append(MirroredImage(source=mapping.source, target=mapping.target))
    return tuple(mirrored)


def _skopeo_copy_args(
    mapping: ImageTargetMapping,
    *,
    destination_auth_file: str | None = None,
) -> list[str]:
    args = [
        "skopeo",
        "copy",
        "--dest-tls-verify=false",
    ]
    if destination_auth_file is not None:
        args.extend(["--dest-authfile", destination_auth_file])
    args.extend(
        [
            "docker://"
            f"{canonicalize_digest_reference(mapping.mirror_source or mapping.source)}",
            f"docker://{mapping.target}",
        ]
    )
    return args


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
