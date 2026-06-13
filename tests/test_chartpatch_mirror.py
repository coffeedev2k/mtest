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


def test_mirror_canonicalizes_source_with_both_tag_and_digest() -> None:
    runner = RecordingRunner()

    mirror_image_mappings(
        (
            ImageTargetMapping(
                source="public.ecr.aws/team/app:1.2.3@sha256:abcdef",
                target="localhost:5000/public.ecr.aws/team/app@sha256:abcdef",
            ),
        ),
        runner,
    )

    assert runner.calls[0][-2:] == (
        "docker://public.ecr.aws/team/app@sha256:abcdef",
        "docker://localhost:5000/public.ecr.aws/team/app@sha256:abcdef",
    )


def test_mirror_uses_destination_authfile_without_credentials_in_args() -> None:
    runner = RecordingRunner()

    mirror_image_mappings(
        (
            ImageTargetMapping(
                source="docker.io/example/app:1.0",
                target="localhost:5000/docker.io/example/app:1.0",
            ),
        ),
        runner,
        destination_auth_file="/tmp/registry-auth.json",
    )

    assert runner.calls[0][2:5] == (
        "--dest-tls-verify=false",
        "--dest-authfile",
        "/tmp/registry-auth.json",
    )


def test_mirror_uses_configured_alternate_source() -> None:
    runner = RecordingRunner()

    mirror_image_mappings(
        (
            ImageTargetMapping(
                source="appscode/kubed:v0.13.2",
                target="localhost:5000/docker.io/appscode/kubed:v0.13.2",
                mirror_source=(
                    "docker.io/rancher/mirrored-appscode-kubed:v0.13.2"
                ),
            ),
        ),
        runner,
    )

    assert runner.calls[0][-2:] == (
        "docker://docker.io/rancher/mirrored-appscode-kubed:v0.13.2",
        "docker://localhost:5000/docker.io/appscode/kubed:v0.13.2",
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
