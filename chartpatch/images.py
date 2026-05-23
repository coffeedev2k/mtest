from __future__ import annotations

from typing import Any

import yaml


class ManifestImageDiscoveryError(ValueError):
    """Raised when rendered manifests cannot provide container images."""


def discover_manifest_images(rendered_manifests: str) -> tuple[str, ...]:
    """Return unique container image references from rendered Kubernetes YAML."""
    try:
        documents = yaml.safe_load_all(rendered_manifests)
        images = {
            image
            for document in documents
            for image in _iter_container_images(document)
        }
    except yaml.YAMLError as exc:
        raise ManifestImageDiscoveryError(
            f"invalid rendered manifest YAML: {exc}"
        ) from None

    if not images:
        raise ManifestImageDiscoveryError(
            "rendered manifests contain no discoverable container images"
        )
    return tuple(sorted(images))


def _iter_container_images(node: Any) -> tuple[str, ...]:
    images: list[str] = []
    _collect_container_images(node, images)
    return tuple(images)


def _collect_container_images(node: Any, images: list[str]) -> None:
    if isinstance(node, dict):
        for field in ("containers", "initContainers"):
            containers = node.get(field)
            if isinstance(containers, list):
                for container in containers:
                    if isinstance(container, dict):
                        image = container.get("image")
                        if isinstance(image, str) and image:
                            images.append(image)

        for value in node.values():
            _collect_container_images(value, images)
        return

    if isinstance(node, list):
        for item in node:
            _collect_container_images(item, images)
