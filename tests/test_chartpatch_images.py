from __future__ import annotations

import pytest

from chartpatch.images import ManifestImageDiscoveryError, discover_manifest_images


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
