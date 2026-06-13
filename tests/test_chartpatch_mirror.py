from __future__ import annotations

from collections.abc import Sequence

import pytest

from chartpatch.images import ImageTargetMapping
from chartpatch.mirror import ImageMirrorError, MirroredImage, mirror_image_mappings
from chartpatch.runner import CommandResult


class RecordingRunner:
    def __init__(self, results: Sequence[CommandResult] | None = None) -> None:
        self.results = list(results or ())
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str]) -> CommandResult:
        call = tuple(args)
        self.calls.append(call)
        if self.results:
            return self.results.pop(0)
        return CommandResult(call, 0, "copied\n", "")


def test_mirror_builds_exact_skopeo_copy_command() -> None:
    runner = RecordingRunner()

    result = mirror_image_mappings(
        (
            ImageTargetMapping(
                source="docker.io/example/app:1.0",
                target="localhost:5000/docker.io/example/app:1.0",
            ),
        ),
        runner,
    )

    assert runner.calls == [
        (
            "skopeo",
            "copy",
            "--dest-tls-verify=false",
            "docker://docker.io/example/app:1.0",
            "docker://localhost:5000/docker.io/example/app:1.0",
        ),
    ]
    assert result == (
        MirroredImage(
            source="docker.io/example/app:1.0",
            target="localhost:5000/docker.io/example/app:1.0",
        ),
    )


def test_mirror_copies_multiple_mappings_in_input_order() -> None:
    runner = RecordingRunner()
    mappings = (
        ImageTargetMapping(
            source="docker.io/example/app:1.0",
            target="localhost:5000/docker.io/example/app:1.0",
        ),
        ImageTargetMapping(
            source="registry.example.com/setup:2.0",
            target="localhost:5000/registry.example.com/setup:2.0",
        ),
    )

    result = mirror_image_mappings(mappings, runner)

    assert runner.calls == [
        (
            "skopeo",
            "copy",
            "--dest-tls-verify=false",
            "docker://docker.io/example/app:1.0",
            "docker://localhost:5000/docker.io/example/app:1.0",
        ),
        (
            "skopeo",
            "copy",
            "--dest-tls-verify=false",
            "docker://registry.example.com/setup:2.0",
            "docker://localhost:5000/registry.example.com/setup:2.0",
        ),
    ]
    assert result == (
        MirroredImage(
            source="docker.io/example/app:1.0",
            target="localhost:5000/docker.io/example/app:1.0",
        ),
        MirroredImage(
            source="registry.example.com/setup:2.0",
            target="localhost:5000/registry.example.com/setup:2.0",
        ),
    )


def test_mirror_stops_on_first_failed_copy_and_reports_details() -> None:
    failed = CommandResult(
        (
            "skopeo",
            "copy",
            "--dest-tls-verify=false",
            "docker://docker.io/example/app:1.0",
            "docker://localhost:5000/docker.io/example/app:1.0",
        ),
        17,
        "copy stdout\n",
        "copy stderr\n",
    )
    runner = RecordingRunner((failed,))

    with pytest.raises(ImageMirrorError) as exc_info:
        mirror_image_mappings(
            (
                ImageTargetMapping(
                    source="docker.io/example/app:1.0",
                    target="localhost:5000/docker.io/example/app:1.0",
                ),
                ImageTargetMapping(
                    source="registry.example.com/setup:2.0",
                    target="localhost:5000/registry.example.com/setup:2.0",
                ),
            ),
            runner,
        )

    message = str(exc_info.value)
    assert "image mirror failed" in message
    assert "source image: docker.io/example/app:1.0" in message
    assert "target image: localhost:5000/docker.io/example/app:1.0" in message
    assert (
        "command: skopeo copy --dest-tls-verify=false "
        "docker://docker.io/example/app:1.0 "
        "docker://localhost:5000/docker.io/example/app:1.0"
    ) in message
    assert "exit status: 17" in message
    assert "copy stdout" in message
    assert "copy stderr" in message
    assert runner.calls == [
        (
            "skopeo",
            "copy",
            "--dest-tls-verify=false",
            "docker://docker.io/example/app:1.0",
            "docker://localhost:5000/docker.io/example/app:1.0",
        ),
    ]


def test_mirror_empty_mapping_list_is_noop() -> None:
    runner = RecordingRunner()

    assert mirror_image_mappings((), runner) == ()
    assert runner.calls == []
