from __future__ import annotations

import pytest

from chartpatch.images import (
    ImageTargetMapping,
    ImageTargetMappingError,
    ManifestImageDiscoveryError,
    discover_manifest_images,
    map_image_targets,
    normalize_image_reference,
)


def test_discovers_image_from_containers() -> None:
    rendered = """
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: app
      image: docker.io/bitnami/nginx:1.27.4
"""

    assert discover_manifest_images(rendered) == ("docker.io/bitnami/nginx:1.27.4",)


def test_discovers_image_from_init_containers() -> None:
    rendered = """
apiVersion: v1
kind: Pod
spec:
  initContainers:
    - name: migrate
      image: registry.example.com/migrate:2.0.0
  containers:
    - name: app
      image: registry.example.com/app:1.0.0
"""

    assert discover_manifest_images(rendered) == (
        "registry.example.com/app:1.0.0",
        "registry.example.com/migrate:2.0.0",
    )


def test_discovers_image_from_ephemeral_containers() -> None:
    rendered = """
apiVersion: v1
kind: Pod
spec:
  ephemeralContainers:
    - name: debugger
      image: registry.example.com/debugger:1.0.0
"""

    assert discover_manifest_images(rendered) == ("registry.example.com/debugger:1.0.0",)


def test_discovers_images_from_all_container_types_sorted() -> None:
    rendered = """
apiVersion: v1
kind: Pod
spec:
  ephemeralContainers:
    - name: debugger
      image: registry.example.com/debugger:1.0.0
  containers:
    - name: app
      image: registry.example.com/app:1.0.0
  initContainers:
    - name: migrate
      image: registry.example.com/migrate:2.0.0
"""

    assert discover_manifest_images(rendered) == (
        "registry.example.com/app:1.0.0",
        "registry.example.com/debugger:1.0.0",
        "registry.example.com/migrate:2.0.0",
    )


def test_deduplicates_images_across_all_container_types() -> None:
    rendered = """
apiVersion: v1
kind: Pod
spec:
  initContainers:
    - name: setup
      image: registry.example.com/shared:1.0.0
  containers:
    - name: app
      image: registry.example.com/shared:1.0.0
    - name: worker
      image: registry.example.com/worker:2.0.0
  ephemeralContainers:
    - name: debugger
      image: registry.example.com/shared:1.0.0
"""

    assert discover_manifest_images(rendered) == (
        "registry.example.com/shared:1.0.0",
        "registry.example.com/worker:2.0.0",
    )


def test_discovers_images_from_deployment_template() -> None:
    rendered = """
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
        - name: app
          image: registry.example.com/app:1.0.0
"""

    assert discover_manifest_images(rendered) == ("registry.example.com/app:1.0.0",)


def test_discovers_images_from_cronjob_template() -> None:
    rendered = """
apiVersion: batch/v1
kind: CronJob
spec:
  jobTemplate:
    spec:
      template:
        spec:
          initContainers:
            - name: setup
              image: registry.example.com/setup:3.0.0
          containers:
            - name: worker
              image: registry.example.com/worker:4.0.0
"""

    assert discover_manifest_images(rendered) == (
        "registry.example.com/setup:3.0.0",
        "registry.example.com/worker:4.0.0",
    )


def test_deduplicates_preserves_tags_and_digests_and_returns_sorted_order() -> None:
    digest = "registry.example.com/app@sha256:0123456789abcdef"
    rendered = f"""
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      initContainers:
        - name: first
          image: {digest}
      containers:
        - name: app
          image: docker.io/bitnami/nginx:1.27.4
        - name: duplicate
          image: docker.io/bitnami/nginx:1.27.4
---
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: digest
      image: {digest}
"""

    assert discover_manifest_images(rendered) == (
        "docker.io/bitnami/nginx:1.27.4",
        digest,
    )


def test_raises_clear_error_when_no_images_are_discovered() -> None:
    rendered = """
---
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: settings
data:
  containers: not-a-pod-spec
"""

    with pytest.raises(ManifestImageDiscoveryError) as exc_info:
        discover_manifest_images(rendered)

    assert "no discoverable container images" in str(exc_info.value)


def test_ignores_empty_yaml_documents_and_documents_without_pod_specs() -> None:
    rendered = """
---
---
apiVersion: v1
kind: Service
metadata:
  name: app
spec:
  ports:
    - port: 80
---
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: app
      image: registry.example.com/app:1.0.0
"""

    assert discover_manifest_images(rendered) == ("registry.example.com/app:1.0.0",)


def test_maps_image_targets_for_docker_hub_and_non_docker_registries() -> None:
    assert map_image_targets(
        (
            "docker.io/bitnami/nginx:1.27.4",
            "quay.io/prometheus/prometheus:v3.0.1",
        ),
        "localhost:5000",
    ) == (
        ImageTargetMapping(
            source="docker.io/bitnami/nginx:1.27.4",
            target="localhost:5000/docker.io/bitnami/nginx:1.27.4",
        ),
        ImageTargetMapping(
            source="quay.io/prometheus/prometheus:v3.0.1",
            target="localhost:5000/quay.io/prometheus/prometheus:v3.0.1",
        ),
    )


def test_maps_image_targets_preserves_tags_and_digests() -> None:
    assert map_image_targets(
        (
            "registry.example.com/app@sha256:0123456789abcdef",
            "registry.example.com/worker:2.0.0",
        ),
        "localhost:5000",
    ) == (
        ImageTargetMapping(
            source="registry.example.com/app@sha256:0123456789abcdef",
            target=(
                "localhost:5000/"
                "registry.example.com/app@sha256:0123456789abcdef"
            ),
        ),
        ImageTargetMapping(
            source="registry.example.com/worker:2.0.0",
            target="localhost:5000/registry.example.com/worker:2.0.0",
        ),
    )


def test_maps_image_targets_deduplicates_and_sorts_sources() -> None:
    assert map_image_targets(
        (
            "quay.io/prometheus/prometheus:v3.0.1",
            "docker.io/bitnami/nginx:1.27.4",
            "quay.io/prometheus/prometheus:v3.0.1",
        ),
        "localhost:5000",
    ) == (
        ImageTargetMapping(
            source="docker.io/bitnami/nginx:1.27.4",
            target="localhost:5000/docker.io/bitnami/nginx:1.27.4",
        ),
        ImageTargetMapping(
            source="quay.io/prometheus/prometheus:v3.0.1",
            target="localhost:5000/quay.io/prometheus/prometheus:v3.0.1",
        ),
    )


def test_maps_image_targets_handles_trailing_registry_slash() -> None:
    assert map_image_targets(
        ("docker.io/bitnami/nginx:1.27.4",),
        "localhost:5000/",
    ) == (
        ImageTargetMapping(
            source="docker.io/bitnami/nginx:1.27.4",
            target="localhost:5000/docker.io/bitnami/nginx:1.27.4",
        ),
    )


def test_maps_image_targets_normalizes_implicit_docker_hub_target() -> None:
    assert map_image_targets(("nginx:latest",), "localhost:5000") == (
        ImageTargetMapping(
            source="nginx:latest",
            target="localhost:5000/docker.io/library/nginx:latest",
        ),
    )


@pytest.mark.parametrize(
    ("source", "normalized"),
    [
        ("nginx:latest", "docker.io/library/nginx:latest"),
        ("bitnami/nginx:1.27.4", "docker.io/bitnami/nginx:1.27.4"),
        ("docker.io/nginx:latest", "docker.io/library/nginx:latest"),
        ("index.docker.io/library/busybox:1.36", "docker.io/library/busybox:1.36"),
        ("quay.io/prometheus/prometheus:v3.0.1", "quay.io/prometheus/prometheus:v3.0.1"),
        ("localhost:5001/example/app:2.0", "localhost:5001/example/app:2.0"),
    ],
)
def test_normalize_image_reference(source: str, normalized: str) -> None:
    assert normalize_image_reference(source) == normalized


def test_maps_image_targets_fails_clearly_for_empty_registry_url() -> None:
    with pytest.raises(ImageTargetMappingError) as exc_info:
        map_image_targets(("docker.io/bitnami/nginx:1.27.4",), "/")

    assert "registry URL must not be empty" in str(exc_info.value)


def test_normalize_image_reference_fails_clearly_for_empty_source() -> None:
    with pytest.raises(ImageTargetMappingError) as exc_info:
        normalize_image_reference(" ")

    assert "image reference must not be empty" in str(exc_info.value)
