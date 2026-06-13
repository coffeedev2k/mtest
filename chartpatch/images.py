from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


class ManifestImageDiscoveryError(ValueError):
    """Raised when rendered manifests cannot provide container images."""


class ImageTargetMappingError(ValueError):
    """Raised when image target mappings cannot be built deterministically."""


@dataclass(frozen=True)
class ImageTargetMapping:
    source: str
    target: str
    mirror_source: str | None = None


def map_image_targets(
    source_images: tuple[str, ...],
    registry_url: str,
    *,
    image_overrides: tuple[tuple[str, str], ...] = (),
) -> tuple[ImageTargetMapping, ...]:
    """Map source image references to deterministic local-registry targets."""
    registry_prefix = registry_url.rstrip("/")
    if not registry_prefix:
        raise ImageTargetMappingError("registry URL must not be empty")

    unique_sources = tuple(sorted(set(source_images)))
    overrides = dict(image_overrides)
    unknown_overrides = tuple(sorted(set(overrides) - set(unique_sources)))
    if unknown_overrides:
        raise ImageTargetMappingError(
            "image overrides do not match rendered images: "
            + ", ".join(unknown_overrides)
        )
    mappings = tuple(
        ImageTargetMapping(
            source=source,
            target=f"{registry_prefix}/{normalize_image_reference(source)}",
            mirror_source=overrides.get(source),
        )
        for source in unique_sources
    )
    if len(mappings) != len(unique_sources):
        raise ImageTargetMappingError(
            "image target mapping failed: expected exactly one target per source image"
        )
    return mappings


def normalize_image_reference(image_reference: str) -> str:
    """Return a deterministic image reference suffix for local registry targets."""
    reference = local_target_reference(image_reference.strip())
    if not reference:
        raise ImageTargetMappingError("image reference must not be empty")

    first_component, separator, remainder = reference.partition("/")
    if separator and _is_registry_component(first_component):
        registry = first_component
        repository = remainder
    else:
        registry = "docker.io"
        repository = reference

    if registry == "index.docker.io":
        registry = "docker.io"

    if registry == "docker.io" and "/" not in repository:
        repository = f"library/{repository}"

    return f"{registry}/{repository}"


def canonicalize_digest_reference(image_reference: str) -> str:
    """Remove a tag when an immutable digest is already present."""
    if "@" not in image_reference:
        return image_reference
    name, digest = image_reference.rsplit("@", 1)
    last_slash = name.rfind("/")
    last_colon = name.rfind(":")
    if last_colon > last_slash:
        name = name[:last_colon]
    return f"{name}@{digest}"


def local_target_reference(image_reference: str) -> str:
    """Convert a digest reference into a tag suitable for a mirror destination."""
    if "@" not in image_reference:
        return image_reference
    name, digest = image_reference.rsplit("@", 1)
    last_slash = name.rfind("/")
    last_colon = name.rfind(":")
    if last_colon > last_slash:
        return name
    algorithm, separator, value = digest.partition(":")
    digest_tag = f"{algorithm}-{value[:16]}" if separator else digest[:24]
    return f"{name}:{digest_tag}"


def discover_manifest_images(
    rendered_manifests: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
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

    if not images and not allow_empty:
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
        for field in ("containers", "initContainers", "ephemeralContainers"):
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


def _is_registry_component(component: str) -> bool:
    return "." in component or ":" in component or component == "localhost"
