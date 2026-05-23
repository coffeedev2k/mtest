from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import tarfile
import tempfile

from .config import ChartPatchConfig
from .images import (
    ImageTargetMapping,
    ImageTargetMappingError,
    ManifestImageDiscoveryError,
    discover_manifest_images,
    map_image_targets,
)
from .mirror import ImageMirrorError, MirroredImage, mirror_image_mappings
from .patch import PatchApplicationError, apply_patch_file
from .runner import CommandResult, CommandRunner


SYNC_STAGE_NAMES = (
    "pull chart",
    "render original chart",
    "discover images",
    "mirror images",
    "apply patch",
    "rewrite images",
    "verify patched chart",
    "package chart",
    "push chart",
)


@dataclass(frozen=True)
class SyncSummary:
    source_repo: str
    source_chart: str
    source_version: str
    patch_file: str
    registry_url: str
    output_chart_ref: str
    stage_names: tuple[str, ...] = SYNC_STAGE_NAMES


def build_sync_summary(config: ChartPatchConfig) -> SyncSummary:
    return SyncSummary(
        source_repo=config.chart.source.repo,
        source_chart=config.chart.source.chart,
        source_version=config.chart.source.version,
        patch_file=config.chart.patch.file,
        registry_url=config.registry.url,
        output_chart_ref=config.chart.output.chart_ref,
    )


def render_sync_summary(summary: SyncSummary) -> str:
    lines = [
        "ChartPatch sync summary",
        f"Source chart repo: {summary.source_repo}",
        f"Source chart name: {summary.source_chart}",
        f"Source chart version: {summary.source_version}",
        f"Patch file: {summary.patch_file}",
        f"Local registry URL: {summary.registry_url}",
        f"Output OCI chart reference: {summary.output_chart_ref}",
        "Planned sync stages:",
    ]
    lines.extend(
        f"  {index}. {stage}" for index, stage in enumerate(summary.stage_names, start=1)
    )
    lines.append("No remote mutation: sync only checks dependencies and prints this summary.")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class SyncWorkspace:
    root: Path
    download_dir: Path
    expected_archive_path: Path
    unpacked_root: Path
    expected_chart_dir: Path
    original_render_path: Path
    logs_dir: Path


@dataclass(frozen=True)
class SyncResult:
    source_repo: str
    source_chart: str
    source_version: str
    workspace_path: Path
    chart_archive_path: Path
    unpacked_chart_path: Path
    original_render_path: Path
    discovered_images: tuple[str, ...]
    image_target_mappings: tuple[ImageTargetMapping, ...] = ()
    mirrored_images: tuple[MirroredImage, ...] = ()
    applied_patch_file: Path | None = None


class SyncWorkflowError(RuntimeError):
    """Raised when the sync workflow cannot complete a required step."""


def run_sync(
    config: ChartPatchConfig,
    *,
    repo_root: Path | None = None,
    runner: CommandRunner | None = None,
) -> SyncResult:
    command_runner = runner or CommandRunner()
    workspace = create_sync_workspace(config, repo_root=repo_root or Path.cwd())

    pull_result = command_runner.run(
        [
            "helm",
            "pull",
            config.chart.source.chart,
            "--repo",
            config.chart.source.repo,
            "--version",
            config.chart.source.version,
            "--destination",
            str(workspace.download_dir),
        ]
    )
    _write_command_logs(workspace.logs_dir, "helm-pull", pull_result)
    if pull_result.returncode != 0:
        raise SyncWorkflowError(_format_command_failure("helm pull failed", pull_result))

    chart_archive = _find_downloaded_chart_archive(
        workspace.download_dir,
        workspace.expected_archive_path,
    )
    _unpack_chart(chart_archive, workspace.unpacked_root)
    unpacked_chart = _find_unpacked_chart_dir(
        workspace.unpacked_root,
        workspace.expected_chart_dir,
    )

    template_result = command_runner.run(
        [
            "helm",
            "template",
            config.chart.name,
            str(unpacked_chart),
        ]
    )
    _write_command_logs(workspace.logs_dir, "helm-template-original", template_result)
    if template_result.returncode != 0:
        raise SyncWorkflowError(
            _format_command_failure("helm template failed", template_result)
        )

    workspace.original_render_path.write_text(template_result.stdout, encoding="utf-8")
    try:
        discovered_images = discover_manifest_images(template_result.stdout)
    except ManifestImageDiscoveryError as exc:
        raise SyncWorkflowError(f"image discovery failed: {exc}") from None
    try:
        image_target_mappings = map_image_targets(
            discovered_images,
            config.registry.url,
        )
    except ImageTargetMappingError as exc:
        raise SyncWorkflowError(f"image target mapping failed: {exc}") from None
    if len(image_target_mappings) != len(discovered_images):
        raise SyncWorkflowError(
            "image target mapping failed: expected exactly one target per discovered image"
        )

    try:
        mirrored_images = mirror_image_mappings(
            image_target_mappings,
            command_runner,
            on_result=lambda index, mapping, result: _write_command_logs(
                workspace.logs_dir,
                f"skopeo-copy-{index}",
                result,
            ),
        )
    except ImageMirrorError as exc:
        raise SyncWorkflowError(str(exc)) from None

    patch_file = _resolve_config_path(repo_root or Path.cwd(), config.chart.patch.file)
    try:
        applied_patch = apply_patch_file(
            unpacked_chart,
            patch_file,
            command_runner,
            on_result=lambda label, result: _write_command_logs(
                workspace.logs_dir,
                label,
                result,
            ),
        )
    except PatchApplicationError as exc:
        raise SyncWorkflowError(str(exc)) from None

    return SyncResult(
        source_repo=config.chart.source.repo,
        source_chart=config.chart.source.chart,
        source_version=config.chart.source.version,
        workspace_path=workspace.root,
        chart_archive_path=chart_archive,
        unpacked_chart_path=unpacked_chart,
        original_render_path=workspace.original_render_path,
        discovered_images=discovered_images,
        image_target_mappings=image_target_mappings,
        mirrored_images=mirrored_images,
        applied_patch_file=applied_patch.patch_file,
    )


def create_sync_workspace(
    config: ChartPatchConfig,
    *,
    repo_root: Path,
) -> SyncWorkspace:
    tmp_root = repo_root / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    root = Path(tempfile.mkdtemp(prefix="chartpatch-sync-", dir=tmp_root))
    download_dir = root / "downloaded"
    unpacked_root = root / "unpacked"
    render_dir = root / "rendered"
    logs_dir = root / "logs"

    for path in (download_dir, unpacked_root, render_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    chart_dir_name = _source_chart_dir_name(config.chart.source.chart)
    return SyncWorkspace(
        root=root,
        download_dir=download_dir,
        expected_archive_path=download_dir
        / f"{chart_dir_name}-{config.chart.source.version}.tgz",
        unpacked_root=unpacked_root,
        expected_chart_dir=unpacked_root / chart_dir_name,
        original_render_path=render_dir / "original.yaml",
        logs_dir=logs_dir,
    )


def render_sync_report(result: SyncResult) -> str:
    lines = [
        "ChartPatch sync report",
        f"Source chart repo: {result.source_repo}",
        f"Source chart name: {result.source_chart}",
        f"Source chart version: {result.source_version}",
        f"Workspace path: {result.workspace_path}",
        f"Pulled chart archive: {result.chart_archive_path}",
        f"Unpacked chart path: {result.unpacked_chart_path}",
        f"Original render output: {result.original_render_path}",
        f"Discovered images: {len(result.discovered_images)}",
    ]
    lines.extend(f"  - {image}" for image in result.discovered_images)
    if result.image_target_mappings:
        lines.append(f"Image target mappings: {len(result.image_target_mappings)}")
        lines.extend(
            f"  - {mapping.source} -> {mapping.target}"
            for mapping in result.image_target_mappings
        )
    if result.mirrored_images:
        lines.append(f"Mirrored images: {len(result.mirrored_images)}")
        lines.extend(
            f"  - {image.source} -> {image.target}" for image in result.mirrored_images
        )
    if result.applied_patch_file is not None:
        lines.append(f"Applied patch: {result.applied_patch_file}")
    return "\n".join(lines) + "\n"


def _resolve_config_path(repo_root: Path, configured_path: str) -> Path:
    path = Path(configured_path)
    if path.is_absolute():
        return path
    return repo_root / path


def _source_chart_dir_name(source_chart: str) -> str:
    name = PurePosixPath(source_chart).name
    if not name or name in {".", ".."}:
        raise SyncWorkflowError(f"invalid chart source name: {source_chart}")
    return name


def _find_downloaded_chart_archive(download_dir: Path, expected_path: Path) -> Path:
    archives = sorted(download_dir.glob("*.tgz"))
    if not archives:
        raise SyncWorkflowError(
            f"missing downloaded chart archive: expected {expected_path}"
        )
    if len(archives) > 1:
        found = ", ".join(str(path) for path in archives)
        raise SyncWorkflowError(f"ambiguous downloaded chart archives: {found}")
    archive = archives[0]
    if archive != expected_path:
        raise SyncWorkflowError(
            f"missing expected downloaded chart archive: expected {expected_path}; "
            f"found {archive}"
        )
    return archive


def _unpack_chart(archive_path: Path, unpacked_root: Path) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(unpacked_root, filter="data")
    except (tarfile.TarError, ValueError, OSError) as exc:
        raise SyncWorkflowError(f"unpack failed for {archive_path}: {exc}") from None


def _find_unpacked_chart_dir(unpacked_root: Path, expected_path: Path) -> Path:
    chart_dirs = sorted(path for path in unpacked_root.iterdir() if path.is_dir())
    if not chart_dirs:
        raise SyncWorkflowError(
            f"missing unpacked chart directory: expected {expected_path}"
        )
    if len(chart_dirs) > 1:
        found = ", ".join(str(path) for path in chart_dirs)
        raise SyncWorkflowError(
            f"ambiguous unpacked chart directories: expected {expected_path}; "
            f"found {found}"
        )
    chart_dir = chart_dirs[0]
    if chart_dir != expected_path:
        raise SyncWorkflowError(
            f"missing expected unpacked chart directory: expected {expected_path}; "
            f"found {chart_dir}"
        )
    return chart_dir


def _write_command_logs(logs_dir: Path, label: str, result: CommandResult) -> None:
    (logs_dir / f"{label}.args.txt").write_text(
        " ".join(result.args) + "\n",
        encoding="utf-8",
    )
    (logs_dir / f"{label}.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (logs_dir / f"{label}.stderr.txt").write_text(result.stderr, encoding="utf-8")


def _format_command_failure(label: str, result: CommandResult) -> str:
    lines = [
        f"{label}: {' '.join(result.args)} exited with code {result.returncode}",
    ]
    if result.stdout.strip():
        lines.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr.strip():
        lines.append(f"stderr:\n{result.stderr.rstrip()}")
    return "\n".join(lines)
