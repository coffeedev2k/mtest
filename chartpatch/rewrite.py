from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .images import ImageTargetMapping


class ImageRewriteVerificationError(RuntimeError):
    """Raised when rewritten chart manifests do not use expected local images."""


class ImageRewriteError(RuntimeError):
    """Raised when chart image references cannot be rewritten."""


@dataclass(frozen=True)
class ImageRewriteChange:
    path: Path
    replacements: int


@dataclass(frozen=True)
class ImageRewriteMapping:
    source: str
    target: str
    replacements: int


@dataclass(frozen=True)
class ImageRewriteResult:
    changes: tuple[ImageRewriteChange, ...]
    mappings: tuple[ImageRewriteMapping, ...]
    unreplaced_sources: tuple[str, ...]

    @property
    def total_replacements(self) -> int:
        return sum(change.replacements for change in self.changes)


def rewrite_chart_images(
    chart_dir: Path,
    mappings: tuple[ImageTargetMapping, ...],
) -> ImageRewriteResult:
    """Replace exact upstream image references in chart-rendering text files."""
    replacement_counts = {mapping.source: 0 for mapping in mappings}
    changes: list[ImageRewriteChange] = []

    try:
        candidates = sorted(chart_dir.rglob("*"))
    except OSError as exc:
        raise ImageRewriteError(
            f"image rewrite failed while scanning {chart_dir}: {exc}"
        ) from None

    for path in candidates:
        if (
            path.is_symlink()
            or not path.is_file()
            or not _is_rewrite_candidate(path, chart_dir)
        ):
            continue

        try:
            original = path.read_bytes().decode("utf-8")
        except OSError as exc:
            raise ImageRewriteError(
                f"image rewrite failed while reading {path}: {exc}"
            ) from None
        except UnicodeDecodeError:
            continue

        updated = original
        replacements = 0
        for mapping in mappings:
            updated, count = _replace_source_outside_target(
                updated,
                mapping.source,
                mapping.target,
            )
            if count == 0:
                continue
            replacement_counts[mapping.source] += count
            replacements += count

        if path.name in {"values.yaml", "values.yml"}:
            updated, structured_replacements = _rewrite_structured_image_values(
                updated,
                mappings,
                replacement_counts,
            )
            replacements += structured_replacements

        if updated != original:
            try:
                path.write_bytes(updated.encode("utf-8"))
            except OSError as exc:
                raise ImageRewriteError(
                    f"image rewrite failed while writing {path}: {exc}"
                ) from None
            changes.append(
                ImageRewriteChange(
                    path=_relative_to(path, chart_dir),
                    replacements=replacements,
                )
            )

    unreplaced = tuple(
        source for source, count in sorted(replacement_counts.items()) if count == 0
    )
    rewrite_mappings = tuple(
        ImageRewriteMapping(
            source=mapping.source,
            target=mapping.target,
            replacements=replacement_counts[mapping.source],
        )
        for mapping in mappings
    )
    return ImageRewriteResult(
        changes=tuple(changes),
        mappings=rewrite_mappings,
        unreplaced_sources=unreplaced,
    )


def _replace_source_outside_target(
    text: str,
    source: str,
    target: str,
) -> tuple[str, int]:
    """Rewrite source references without nesting an already-local target."""
    if source == target:
        return text, 0
    parts = text.split(target)
    replacements = sum(part.count(source) for part in parts)
    if replacements == 0:
        return text, 0
    return target.join(part.replace(source, target) for part in parts), replacements


def verify_image_mapping_complete(
    discovered_images: tuple[str, ...],
    mappings: tuple[ImageTargetMapping, ...],
) -> tuple[ImageTargetMapping, ...]:
    mappings_by_source = {
        mapping.source: mapping for mapping in mappings if mapping.target
    }
    missing_sources = tuple(
        image for image in sorted(set(discovered_images)) if image not in mappings_by_source
    )
    if missing_sources:
        formatted = "\n".join(f"  - {image}" for image in missing_sources)
        raise ImageRewriteVerificationError(
            "image rewrite verification failed: missing target mappings\n"
            f"{formatted}"
        )
    return tuple(mappings_by_source[image] for image in sorted(set(discovered_images)))


def verify_patched_rendered_images(
    original_images: tuple[str, ...],
    mappings: tuple[ImageTargetMapping, ...],
    patched_images: tuple[str, ...],
    registry_url: str,
) -> tuple[str, ...]:
    """Verify patched rendered manifests only reference expected local images."""
    expected_mappings = verify_image_mapping_complete(original_images, mappings)
    expected_targets = {mapping.target for mapping in expected_mappings}
    patched_image_set = set(patched_images)
    registry_prefix = f"{registry_url.rstrip('/')}/"

    missing_targets = tuple(sorted(expected_targets - patched_image_set))
    leaked_sources = tuple(sorted(set(original_images) & patched_image_set))
    non_local_images = tuple(
        sorted(image for image in patched_image_set if not image.startswith(registry_prefix))
    )

    failures: list[str] = []
    if missing_targets:
        failures.append(
            "missing local targets\n"
            + "\n".join(f"  - {image}" for image in missing_targets)
        )
    if leaked_sources:
        failures.append(
            "leaked upstream images\n"
            + "\n".join(f"  - {image}" for image in leaked_sources)
        )
    if non_local_images:
        failures.append(
            "non-local rendered images\n"
            + "\n".join(f"  - {image}" for image in non_local_images)
        )

    if failures:
        raise ImageRewriteVerificationError(
            "patched render image verification failed: " + "\n".join(failures)
        )

    return tuple(sorted(patched_image_set))


def _is_rewrite_candidate(path: Path, chart_dir: Path) -> bool:
    relative = _relative_to(path, chart_dir)
    if ".git" in relative.parts:
        return False
    if relative.suffix in {".yaml", ".yml", ".tpl", ".gotmpl"}:
        return True
    return relative.name in {"Chart.yaml", "values.yaml", "values.yml"}


def _rewrite_structured_image_values(
    text: str,
    mappings: tuple[ImageTargetMapping, ...],
    replacement_counts: dict[str, int],
) -> tuple[str, int]:
    locations: dict[
        tuple[str, str],
        tuple[str, str, tuple[str, ...]],
    ] = {}
    grouped_sources: dict[tuple[str, str], list[str]] = {}
    for mapping in mappings:
        source_location = _image_location(mapping.source)
        target_location = _image_location(mapping.target)
        if source_location is None or target_location is None:
            continue
        grouped_sources.setdefault(source_location, []).append(mapping.source)
        locations[source_location] = (
            target_location[0],
            target_location[1],
            tuple(grouped_sources[source_location]),
        )

    lines = text.splitlines(keepends=True)
    entries = _yaml_image_entries(lines)
    replacements = 0
    for index, indent, key, repository in entries:
        if key != "repository" or not isinstance(repository, str):
            continue
        siblings = {
            sibling_key: (sibling_index, sibling_value)
            for sibling_index, sibling_indent, sibling_key, sibling_value in entries
            if sibling_indent == indent
            and _same_yaml_mapping(lines, index, sibling_index, indent)
        }
        registry_entry = siblings.get("registry")
        default_registry_entry = siblings.get("defaultRegistry")
        if registry_entry is None and default_registry_entry is None:
            direct_rewrite = _direct_repository_rewrite(repository, mappings)
            if direct_rewrite is not None:
                target_repository, sources = direct_rewrite
                replacements += _replace_yaml_scalar(lines, index, target_repository)
                replacements += _clear_retagged_digest(
                    lines,
                    siblings,
                    sources,
                    mappings,
                )
                for source in sources:
                    replacement_counts[source] += 1
            continue
        registry = registry_entry[1] if registry_entry is not None else None
        if registry in (None, "", "~"):
            registry = (
                default_registry_entry[1]
                if default_registry_entry is not None
                else None
            )
        if not isinstance(registry, str):
            continue

        rewrite = locations.get((registry, repository))
        if rewrite is None:
            continue
        target_registry, target_repository, sources = rewrite
        registry_index = (
            registry_entry[0]
            if registry_entry is not None
            else default_registry_entry[0]
            if default_registry_entry is not None
            else None
        )
        if registry_index is None:
            continue

        replacements += _replace_yaml_scalar(
            lines,
            registry_index,
            target_registry,
        )
        replacements += _replace_yaml_scalar(
            lines,
            index,
            target_repository,
        )
        replacements += _clear_retagged_digest(
            lines,
            siblings,
            sources,
            mappings,
        )
        for source in sources:
            replacement_counts[source] += 1

    return "".join(lines), replacements


def _direct_repository_rewrite(
    repository: str,
    mappings: tuple[ImageTargetMapping, ...],
) -> tuple[str, tuple[str, ...]] | None:
    matches = [
        mapping
        for mapping in mappings
        if _image_name_without_tag(mapping.source) == repository
        or (
            _image_name_without_tag(mapping.source) == f"docker.io/{repository}"
        )
    ]
    if not matches:
        return None
    targets = {_image_name_without_tag(mapping.target) for mapping in matches}
    if len(targets) != 1:
        return None
    return next(iter(targets)), tuple(mapping.source for mapping in matches)


def _clear_retagged_digest(
    lines: list[str],
    siblings: dict[str, tuple[int, object]],
    sources: tuple[str, ...],
    mappings: tuple[ImageTargetMapping, ...],
) -> int:
    digest_entry = siblings.get("digest")
    if digest_entry is None:
        return 0
    mappings_by_source = {mapping.source: mapping for mapping in mappings}
    if not any(
        "@" in source and "@" not in mappings_by_source[source].target
        for source in sources
    ):
        return 0
    return _replace_yaml_scalar(lines, digest_entry[0], "")


def _yaml_image_entries(
    lines: list[str],
) -> tuple[tuple[int, int, str, object], ...]:
    entries: list[tuple[int, int, str, object]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "{{" in stripped:
            continue
        try:
            value = yaml.safe_load(stripped)
        except yaml.YAMLError:
            continue
        if not isinstance(value, dict) or len(value) != 1:
            continue
        key, scalar = next(iter(value.items()))
        if key not in {
            "registry",
            "defaultRegistry",
            "repository",
            "tag",
            "digest",
        }:
            continue
        if scalar is not None and not isinstance(scalar, str):
            continue
        entries.append((index, len(line) - len(line.lstrip()), key, scalar))
    return tuple(entries)


def _same_yaml_mapping(
    lines: list[str],
    first_index: int,
    second_index: int,
    indent: int,
) -> bool:
    start, end = sorted((first_index, second_index))
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent < indent:
            return False
    return True


def _replace_yaml_scalar(lines: list[str], index: int, value: str) -> int:
    line = lines[index]
    newline = "\n" if line.endswith("\n") else ""
    content = line[:-1] if newline else line
    indent = content[: len(content) - len(content.lstrip())]
    key = content.lstrip().split(":", 1)[0]
    updated = f"{indent}{key}: {value}{newline}"
    if updated == line:
        return 0
    lines[index] = updated
    return 1


def _image_location(reference: str) -> tuple[str, str] | None:
    name = _image_name_without_tag(reference)
    registry, separator, repository = name.partition("/")
    if not separator or not registry or not repository:
        return None
    return registry, repository


def _image_name_without_tag(reference: str) -> str:
    name = reference.rsplit("@", 1)[0]
    last_slash = name.rfind("/")
    last_colon = name.rfind(":")
    if last_colon > last_slash:
        name = name[:last_colon]
    return name


def _relative_to(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path
