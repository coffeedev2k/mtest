from __future__ import annotations

from pathlib import Path

import pytest

from chartpatch.images import ImageTargetMapping
from chartpatch.rewrite import (
    ImageRewriteError,
    ImageRewriteVerificationError,
    rewrite_chart_images,
    verify_image_mapping_complete,
)


def test_rewrites_exact_image_references_in_chart_text_files(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text(
        "image: docker.io/bitnami/nginx:1.27.4\n"
        "note: quay.io/other/sidecar:9.9.9\n",
        encoding="utf-8",
    )

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="docker.io/bitnami/nginx:1.27.4",
                target="localhost:5000/docker.io/bitnami/nginx:1.27.4",
            ),
        ),
    )

    assert values.read_text(encoding="utf-8") == (
        "image: localhost:5000/docker.io/bitnami/nginx:1.27.4\n"
        "note: quay.io/other/sidecar:9.9.9\n"
    )
    assert result.total_replacements == 1
    assert result.mappings[0].source == "docker.io/bitnami/nginx:1.27.4"
    assert result.mappings[0].target == "localhost:5000/docker.io/bitnami/nginx:1.27.4"
    assert result.mappings[0].replacements == 1
    assert result.unreplaced_sources == ()


def test_rewrites_multiple_occurrences_across_files(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    (chart / "values.yaml").write_text(
        "image: docker.io/example/app:1.0\n"
        "backup: docker.io/example/app:1.0\n",
        encoding="utf-8",
    )
    templates = chart / "templates"
    templates.mkdir()
    (templates / "deployment.yaml").write_text(
        "image: docker.io/example/app:1.0\n",
        encoding="utf-8",
    )

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="docker.io/example/app:1.0",
                target="localhost:5000/docker.io/example/app:1.0",
            ),
        ),
    )

    assert result.total_replacements == 3
    assert sorted(change.path for change in result.changes) == [
        Path("templates/deployment.yaml"),
        Path("values.yaml"),
    ]


def test_rewrites_multiple_different_images_to_different_targets(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text(
        "app: docker.io/example/app:1.0\n"
        "setup: registry.example.com/setup:2.0\n",
        encoding="utf-8",
    )

    rewrite_chart_images(
        chart,
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
    )

    assert values.read_text(encoding="utf-8") == (
        "app: localhost:5000/docker.io/example/app:1.0\n"
        "setup: localhost:5000/registry.example.com/setup:2.0\n"
    )


def test_leaves_files_unchanged_when_no_mapped_references_are_present(
    tmp_path: Path,
) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    original = "image: docker.io/example/not-discovered:9.9\n"
    values.write_text(original, encoding="utf-8")

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="docker.io/example/app:1.0",
                target="localhost:5000/docker.io/example/app:1.0",
            ),
        ),
    )

    assert values.read_text(encoding="utf-8") == original
    assert result.changes == ()
    assert result.total_replacements == 0
    assert result.mappings[0].replacements == 0
    assert result.unreplaced_sources == ("docker.io/example/app:1.0",)


def test_leaves_unrelated_values_and_unsupported_files_unchanged(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text(
        "image: docker.io/example/app:1.0\n"
        "other: docker.io/example/not-discovered:9.9\n",
        encoding="utf-8",
    )
    notes = chart / "README.md"
    notes.write_text("docker.io/example/app:1.0\n", encoding="utf-8")

    rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="docker.io/example/app:1.0",
                target="localhost:5000/docker.io/example/app:1.0",
            ),
        ),
    )

    assert "docker.io/example/not-discovered:9.9" in values.read_text(encoding="utf-8")
    assert notes.read_text(encoding="utf-8") == "docker.io/example/app:1.0\n"


def test_skips_binary_supported_files_safely(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    binary = chart / "values.yaml"
    binary.write_bytes(b"\xff\xfe\x00docker.io/example/app:1.0")

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="docker.io/example/app:1.0",
                target="localhost:5000/docker.io/example/app:1.0",
            ),
        ),
    )

    assert binary.read_bytes() == b"\xff\xfe\x00docker.io/example/app:1.0"
    assert result.total_replacements == 0
    assert result.unreplaced_sources == ("docker.io/example/app:1.0",)


def test_rewrite_fails_clearly_when_candidate_file_cannot_be_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text("image: docker.io/example/app:1.0\n", encoding="utf-8")
    original_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == values:
            raise OSError("permission denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    with pytest.raises(ImageRewriteError) as exc_info:
        rewrite_chart_images(
            chart,
            (
                ImageTargetMapping(
                    source="docker.io/example/app:1.0",
                    target="localhost:5000/docker.io/example/app:1.0",
                ),
            ),
        )

    message = str(exc_info.value)
    assert "image rewrite failed while reading" in message
    assert "permission denied" in message


def test_rewrite_fails_clearly_when_candidate_file_cannot_be_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text("image: docker.io/example/app:1.0\n", encoding="utf-8")
    original_write_bytes = Path.write_bytes

    def write_bytes(path: Path, data: bytes) -> int:
        if path == values:
            raise OSError("read-only file system")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", write_bytes)

    with pytest.raises(ImageRewriteError) as exc_info:
        rewrite_chart_images(
            chart,
            (
                ImageTargetMapping(
                    source="docker.io/example/app:1.0",
                    target="localhost:5000/docker.io/example/app:1.0",
                ),
            ),
        )

    message = str(exc_info.value)
    assert "image rewrite failed while writing" in message
    assert "read-only file system" in message


def test_verification_fails_when_image_mapping_is_incomplete() -> None:
    with pytest.raises(ImageRewriteVerificationError) as exc_info:
        verify_image_mapping_complete(
            ("docker.io/example/app:1.0", "registry.example.com/setup:2.0"),
            (
                ImageTargetMapping(
                    source="docker.io/example/app:1.0",
                    target="localhost:5000/docker.io/example/app:1.0",
                ),
            ),
        )

    message = str(exc_info.value)
    assert "missing target mappings" in message
    assert "registry.example.com/setup:2.0" in message


def _write_chart(tmp_path: Path) -> Path:
    chart = tmp_path / "chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text(
        "apiVersion: v2\nname: chart\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    return chart
