from __future__ import annotations

from pathlib import Path

import pytest

from chartpatch.images import ImageTargetMapping
from chartpatch.rewrite import (
    ImageRewriteError,
    ImageRewriteVerificationError,
    rewrite_chart_images,
    verify_image_mapping_complete,
    verify_patched_rendered_images,
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


def test_rewrites_structured_registry_and_repository_values(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text(
        "controller:\n"
        "  image:\n"
        "    registry: ~\n"
        "    defaultRegistry: reg.example.io\n"
        "    repository: team/controller\n"
        "    tag: ~\n"
        "readiness:\n"
        "  image:\n"
        "    registry: ghcr.io\n"
        "    repository: team/readiness\n"
        "    tag: latest\n",
        encoding="utf-8",
    )

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="reg.example.io/team/controller:v1.0.0",
                target="localhost:5000/reg.example.io/team/controller:v1.0.0",
            ),
            ImageTargetMapping(
                source="ghcr.io/team/readiness:latest",
                target="localhost:5000/ghcr.io/team/readiness:latest",
            ),
        ),
    )

    assert values.read_text(encoding="utf-8") == (
        "controller:\n"
        "  image:\n"
        "    registry: localhost:5000\n"
        "    defaultRegistry: reg.example.io\n"
        "    repository: reg.example.io/team/controller\n"
        "    tag: ~\n"
        "readiness:\n"
        "  image:\n"
        "    registry: localhost:5000\n"
        "    repository: ghcr.io/team/readiness\n"
        "    tag: latest\n"
    )
    assert result.total_replacements == 4
    assert result.unreplaced_sources == ()


def test_rewrites_full_repository_value_when_tag_is_stored_separately(
    tmp_path: Path,
) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text(
        "image:\n"
        "  repository: public.ecr.aws/eks/aws-load-balancer-controller\n"
        "  tag: v3.4.0\n",
        encoding="utf-8",
    )

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="public.ecr.aws/eks/aws-load-balancer-controller:v3.4.0",
                target=(
                    "localhost:5000/public.ecr.aws/eks/"
                    "aws-load-balancer-controller:v3.4.0"
                ),
            ),
        ),
    )

    assert values.read_text(encoding="utf-8") == (
        "image:\n"
        "  repository: localhost:5000/public.ecr.aws/eks/"
        "aws-load-balancer-controller\n"
        "  tag: v3.4.0\n"
    )
    assert result.unreplaced_sources == ()


def test_rewrites_docker_hub_repository_shorthand(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text(
        "image:\n"
        "  repository: aquasec/kube-bench\n"
        "  tag: v0.8.0\n",
        encoding="utf-8",
    )

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source="aquasec/kube-bench:v0.8.0",
                target="localhost:5000/docker.io/aquasec/kube-bench:v0.8.0",
            ),
        ),
    )

    assert "repository: localhost:5000/docker.io/aquasec/kube-bench" in (
        values.read_text(encoding="utf-8")
    )
    assert result.unreplaced_sources == ()


def test_clears_separate_digest_when_local_target_uses_tag(tmp_path: Path) -> None:
    chart = _write_chart(tmp_path)
    values = chart / "values.yaml"
    values.write_text(
        "image:\n"
        "  repository: public.ecr.aws/karpenter/controller\n"
        "  tag: 1.11.1\n"
        "  digest: sha256:abcdef\n",
        encoding="utf-8",
    )

    result = rewrite_chart_images(
        chart,
        (
            ImageTargetMapping(
                source=(
                    "public.ecr.aws/karpenter/controller:"
                    "1.11.1@sha256:abcdef"
                ),
                target=(
                    "localhost:5000/public.ecr.aws/"
                    "karpenter/controller:1.11.1"
                ),
            ),
        ),
    )

    rewritten = values.read_text(encoding="utf-8")
    assert "repository: localhost:5000/public.ecr.aws/karpenter/controller" in rewritten
    assert "digest: \n" in rewritten
    assert result.unreplaced_sources == ()


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


def test_patched_render_verification_passes_for_expected_local_targets() -> None:
    final_images = verify_patched_rendered_images(
        ("docker.io/example/app:1.0", "registry.example.com/setup:2.0"),
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
        (
            "localhost:5000/docker.io/example/app:1.0",
            "localhost:5000/registry.example.com/setup:2.0",
        ),
        "localhost:5000",
    )

    assert final_images == (
        "localhost:5000/docker.io/example/app:1.0",
        "localhost:5000/registry.example.com/setup:2.0",
    )


def test_patched_render_verification_fails_when_local_target_is_missing() -> None:
    with pytest.raises(ImageRewriteVerificationError) as exc_info:
        verify_patched_rendered_images(
            ("docker.io/example/app:1.0",),
            (
                ImageTargetMapping(
                    source="docker.io/example/app:1.0",
                    target="localhost:5000/docker.io/example/app:1.0",
                ),
            ),
            ("localhost:5000/docker.io/example/other:1.0",),
            "localhost:5000",
        )

    message = str(exc_info.value)
    assert "missing local targets" in message
    assert "localhost:5000/docker.io/example/app:1.0" in message


def test_patched_render_verification_fails_when_upstream_image_leaks() -> None:
    with pytest.raises(ImageRewriteVerificationError) as exc_info:
        verify_patched_rendered_images(
            ("docker.io/example/app:1.0",),
            (
                ImageTargetMapping(
                    source="docker.io/example/app:1.0",
                    target="localhost:5000/docker.io/example/app:1.0",
                ),
            ),
            (
                "docker.io/example/app:1.0",
                "localhost:5000/docker.io/example/app:1.0",
            ),
            "localhost:5000",
        )

    message = str(exc_info.value)
    assert "leaked upstream images" in message
    assert "docker.io/example/app:1.0" in message


def test_patched_render_verification_fails_when_rendered_image_is_not_local() -> None:
    with pytest.raises(ImageRewriteVerificationError) as exc_info:
        verify_patched_rendered_images(
            ("docker.io/example/app:1.0",),
            (
                ImageTargetMapping(
                    source="docker.io/example/app:1.0",
                    target="localhost:5000/docker.io/example/app:1.0",
                ),
            ),
            (
                "localhost:5000/docker.io/example/app:1.0",
                "quay.io/example/sidecar:2.0",
            ),
            "localhost:5000/",
        )

    message = str(exc_info.value)
    assert "non-local rendered images" in message
    assert "quay.io/example/sidecar:2.0" in message


def test_patched_render_verification_uses_exact_upstream_image_comparison() -> None:
    final_images = verify_patched_rendered_images(
        ("docker.io/example/app:1.0",),
        (
            ImageTargetMapping(
                source="docker.io/example/app:1.0",
                target="localhost:5000/docker.io/example/app:1.0",
            ),
        ),
        ("localhost:5000/docker.io/example/app:1.0",),
        "localhost:5000",
    )

    assert final_images == ("localhost:5000/docker.io/example/app:1.0",)


def _write_chart(tmp_path: Path) -> Path:
    chart = tmp_path / "chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text(
        "apiVersion: v2\nname: chart\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    return chart
