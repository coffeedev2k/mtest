from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
            count = updated.count(mapping.source)
            if count == 0:
                continue
            updated = updated.replace(mapping.source, mapping.target)
            replacement_counts[mapping.source] += count
            replacements += count

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


def _is_rewrite_candidate(path: Path, chart_dir: Path) -> bool:
    relative = _relative_to(path, chart_dir)
    if ".git" in relative.parts:
        return False
    if relative.suffix in {".yaml", ".yml", ".tpl", ".gotmpl"}:
        return True
    return relative.name in {"Chart.yaml", "values.yaml", "values.yml"}


def _relative_to(path: Path, root: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path
