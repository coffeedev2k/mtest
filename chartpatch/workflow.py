from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile

from .config import ChartPatchConfig, NormalizedChartConfig, normalize_chart_entries
from .helm import run_helm_lint, run_helm_package, run_helm_push, run_helm_template
from .images import (
    ImageTargetMapping,
    ImageTargetMappingError,
    ManifestImageDiscoveryError,
    discover_manifest_images,
    map_image_targets,
)
from .mirror import ImageMirrorError, MirroredImage, mirror_image_mappings
from .patch import PatchApplicationError, apply_patch_file
from .rewrite import (
    ImageRewriteError,
    ImageRewriteMapping,
    ImageRewriteVerificationError,
    rewrite_chart_images,
    verify_image_mapping_complete,
    verify_patched_rendered_images,
)
from .runner import CommandResult, CommandRunner


STAGE_DEPENDENCY_CHECK = "dependency check"
STAGE_CHART_PULL = "chart pull"
STAGE_ORIGINAL_RENDER = "original render"
STAGE_IMAGE_DISCOVERY = "image discovery"
STAGE_IMAGE_MIRROR = "image mirror"
STAGE_PATCH_APPLY = "patch apply"
STAGE_IMAGE_REWRITE = "image rewrite"
STAGE_REWRITE_VERIFICATION = "rewrite verification"
STAGE_FINAL_VERIFICATION = "final verification"
STAGE_PACKAGE = "package"
STAGE_OCI_PUSH = "OCI push"

SYNC_STAGE_NAMES = (
    STAGE_CHART_PULL,
    STAGE_ORIGINAL_RENDER,
    STAGE_IMAGE_DISCOVERY,
    STAGE_IMAGE_MIRROR,
    STAGE_PATCH_APPLY,
    STAGE_IMAGE_REWRITE,
    STAGE_REWRITE_VERIFICATION,
    STAGE_FINAL_VERIFICATION,
    STAGE_PACKAGE,
    STAGE_OCI_PUSH,
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


def build_sync_summary(chart: NormalizedChartConfig) -> SyncSummary:
    return SyncSummary(
        source_repo=chart.source_repo,
        source_chart=chart.source_chart,
        source_version=chart.source_version,
        patch_file=chart.patch_file,
        registry_url=chart.registry_url,
        output_chart_ref=chart.output_chart_ref,
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
    lines.append(
        "Remote mutation occurs only after verification, packaging, and push gates pass."
    )
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class SyncWorkspace:
    root: Path
    download_dir: Path
    expected_archive_path: Path
    unpacked_root: Path
    expected_chart_dir: Path
    original_render_path: Path
    patched_render_path: Path
    package_output_dir: Path
    logs_dir: Path


@dataclass(frozen=True)
class SyncResult:
    source_repo: str
    source_chart: str
    source_version: str
    patch_file: str
    registry_url: str
    output_chart_ref: str
    workspace_path: Path
    chart_archive_path: Path
    unpacked_chart_path: Path
    original_render_path: Path
    discovered_images: tuple[str, ...]
    patched_render_path: Path | None = None
    final_rendered_images: tuple[str, ...] = ()
    image_target_mappings: tuple[ImageTargetMapping, ...] = ()
    mirrored_images: tuple[MirroredImage, ...] = ()
    applied_patch_file: Path | None = None
    image_rewrites: tuple[ImageRewriteMapping, ...] = ()
    rewritten_files: tuple[Path, ...] = ()
    rewrite_replacements: int = 0
    final_helm_lint_verified: bool = False
    final_helm_template_verified: bool = False
    packaged_chart_path: Path | None = None
    pushed_chart_ref: str | None = None


@dataclass(frozen=True)
class ChartSyncReport:
    chart_name: str
    source_repo: str
    source_chart: str
    source_version: str
    patch_file: str
    registry_url: str
    output_chart_ref: str
    result: SyncResult | None = None
    error: SyncWorkflowError | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError("chart sync report must have exactly one result or error")

    @property
    def succeeded(self) -> bool:
        return self.result is not None


@dataclass(frozen=True)
class MultiChartSyncReport:
    entries: tuple[ChartSyncReport, ...]

    @property
    def succeeded(self) -> bool:
        return all(entry.succeeded for entry in self.entries)


class SyncWorkflowError(RuntimeError):
    """Raised when the sync workflow cannot complete a required step."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        source_repo: str | None = None,
        source_chart: str | None = None,
        source_version: str | None = None,
        workspace_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.source_repo = source_repo
        self.source_chart = source_chart
        self.source_version = source_version
        self.workspace_path = workspace_path

    def __str__(self) -> str:
        if self.stage is None:
            return self.message
        return f"stage {self.stage} failed: {self.message}"


def build_successful_chart_sync_report(
    chart: NormalizedChartConfig,
    result: SyncResult,
) -> ChartSyncReport:
    return ChartSyncReport(
        chart_name=chart.chart_name,
        source_repo=chart.source_repo,
        source_chart=chart.source_chart,
        source_version=chart.source_version,
        patch_file=chart.patch_file,
        registry_url=chart.registry_url,
        output_chart_ref=chart.output_chart_ref,
        result=result,
    )


def build_failed_chart_sync_report(
    chart: NormalizedChartConfig,
    error: SyncWorkflowError,
) -> ChartSyncReport:
    return ChartSyncReport(
        chart_name=chart.chart_name,
        source_repo=chart.source_repo,
        source_chart=chart.source_chart,
        source_version=chart.source_version,
        patch_file=chart.patch_file,
        registry_url=chart.registry_url,
        output_chart_ref=chart.output_chart_ref,
        error=error,
    )


def aggregate_chart_sync_reports(
    entries: tuple[ChartSyncReport, ...],
) -> MultiChartSyncReport:
    return MultiChartSyncReport(entries=entries)


def run_sync(
    config: ChartPatchConfig,
    *,
    repo_root: Path | None = None,
    runner: CommandRunner | None = None,
) -> SyncResult | MultiChartSyncReport:
    charts = normalize_chart_entries(config)
    if config.is_multi_chart:
        reports: list[ChartSyncReport] = []
        for chart in charts:
            try:
                result = run_single_chart_sync(
                    chart,
                    repo_root=repo_root,
                    runner=runner,
                )
            except SyncWorkflowError as exc:
                reports.append(build_failed_chart_sync_report(chart, exc))
                continue

            reports.append(build_successful_chart_sync_report(chart, result))

        return aggregate_chart_sync_reports(tuple(reports))

    return run_single_chart_sync(
        charts[0],
        repo_root=repo_root,
        runner=runner,
    )


def run_single_chart_sync(
    chart: NormalizedChartConfig,
    *,
    repo_root: Path | None = None,
    runner: CommandRunner | None = None,
) -> SyncResult:
    command_runner = runner or CommandRunner()
    workflow_repo_root = repo_root or Path.cwd()
    try:
        workspace = create_sync_workspace(chart, repo_root=workflow_repo_root)
    except SyncWorkflowError as exc:
        raise _sync_error(chart, None, STAGE_CHART_PULL, exc.message) from None

    pull_result = command_runner.run(
        [
            "helm",
            "pull",
            chart.source_chart,
            "--repo",
            chart.source_repo,
            "--version",
            chart.source_version,
            "--destination",
            str(workspace.download_dir),
        ]
    )
    _write_command_logs(workspace.logs_dir, "helm-pull", pull_result)
    if pull_result.returncode != 0:
        raise _sync_error(
            chart,
            workspace,
            STAGE_CHART_PULL,
            _format_command_failure("helm pull failed", pull_result),
        )

    try:
        chart_archive = _find_downloaded_chart_archive(
            workspace.download_dir,
            workspace.expected_archive_path,
        )
        _unpack_chart(chart_archive, workspace.unpacked_root)
        unpacked_chart = _find_unpacked_chart_dir(
            workspace.unpacked_root,
            workspace.expected_chart_dir,
        )
    except SyncWorkflowError as exc:
        raise _sync_error(chart, workspace, STAGE_CHART_PULL, exc.message) from None

    template_result = run_helm_template(command_runner, chart.chart_name, unpacked_chart)
    _write_command_logs(workspace.logs_dir, "helm-template-original", template_result)
    if template_result.returncode != 0:
        raise _sync_error(
            chart,
            workspace,
            STAGE_ORIGINAL_RENDER,
            _format_command_failure("helm template failed", template_result),
        )

    workspace.original_render_path.write_text(template_result.stdout, encoding="utf-8")
    try:
        discovered_images = discover_manifest_images(template_result.stdout)
    except ManifestImageDiscoveryError as exc:
        raise _sync_error(
            chart,
            workspace,
            STAGE_IMAGE_DISCOVERY,
            f"image discovery failed: {exc}",
        ) from None
    try:
        image_target_mappings = map_image_targets(
            discovered_images,
            chart.registry_url,
        )
    except ImageTargetMappingError as exc:
        raise _sync_error(
            chart,
            workspace,
            STAGE_IMAGE_DISCOVERY,
            f"image target mapping failed: {exc}",
        ) from None
    try:
        verify_image_mapping_complete(discovered_images, image_target_mappings)
    except ImageRewriteVerificationError as exc:
        raise _sync_error(
            chart,
            workspace,
            STAGE_IMAGE_DISCOVERY,
            f"image target mapping failed: {exc}",
        ) from None

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
        raise _sync_error(chart, workspace, STAGE_IMAGE_MIRROR, str(exc)) from None

    patch_file = _resolve_config_path(workflow_repo_root, chart.patch_file)
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
        raise _sync_error(chart, workspace, STAGE_PATCH_APPLY, str(exc)) from None

    try:
        rewrite_result = rewrite_chart_images(unpacked_chart, image_target_mappings)
    except ImageRewriteError as exc:
        raise _sync_error(chart, workspace, STAGE_IMAGE_REWRITE, str(exc)) from None

    patched_template_result = run_helm_template(
        command_runner,
        chart.chart_name,
        unpacked_chart,
    )
    _write_command_logs(
        workspace.logs_dir,
        "helm-template-patched",
        patched_template_result,
    )
    if patched_template_result.returncode != 0:
        raise _sync_error(
            chart,
            workspace,
            STAGE_REWRITE_VERIFICATION,
            _format_command_failure(
                "patched helm template failed",
                patched_template_result,
            ),
        )

    workspace.patched_render_path.write_text(
        patched_template_result.stdout,
        encoding="utf-8",
    )
    try:
        patched_images = discover_manifest_images(patched_template_result.stdout)
    except ManifestImageDiscoveryError as exc:
        raise _sync_error(
            chart,
            workspace,
            STAGE_REWRITE_VERIFICATION,
            f"patched render image discovery failed: {exc}",
        ) from None
    try:
        final_rendered_images = verify_patched_rendered_images(
            discovered_images,
            image_target_mappings,
            patched_images,
            chart.registry_url,
        )
    except ImageRewriteVerificationError as exc:
        raise _sync_error(
            chart,
            workspace,
            STAGE_REWRITE_VERIFICATION,
            str(exc),
        ) from None

    final_helm_lint_verified = False
    if chart.helm_lint:
        lint_result = run_helm_lint(command_runner, unpacked_chart)
        _write_command_logs(workspace.logs_dir, "helm-lint-final", lint_result)
        if lint_result.returncode != 0:
            raise _sync_error(
                chart,
                workspace,
                STAGE_FINAL_VERIFICATION,
                _format_command_failure(
                    "final helm lint verification failed",
                    lint_result,
                ),
            )
        final_helm_lint_verified = True

    final_helm_template_verified = False
    if chart.helm_template:
        final_template_result = run_helm_template(
            command_runner,
            chart.chart_name,
            unpacked_chart,
        )
        _write_command_logs(
            workspace.logs_dir,
            "helm-template-final",
            final_template_result,
        )
        if final_template_result.returncode != 0:
            raise _sync_error(
                chart,
                workspace,
                STAGE_FINAL_VERIFICATION,
                _format_command_failure(
                    "final helm template verification failed",
                    final_template_result,
                ),
            )
        final_helm_template_verified = True

    try:
        shutil.rmtree(unpacked_chart / ".git")
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise _sync_error(
            chart,
            workspace,
            STAGE_PACKAGE,
            f"failed to remove temporary git metadata: {exc}",
        ) from None

    package_result = run_helm_package(
        command_runner,
        unpacked_chart,
        workspace.package_output_dir,
    )
    _write_command_logs(workspace.logs_dir, "helm-package", package_result)
    if package_result.returncode != 0:
        raise _sync_error(
            chart,
            workspace,
            STAGE_PACKAGE,
            _format_command_failure("helm package failed", package_result),
        )
    try:
        packaged_chart = _find_packaged_chart_archive(workspace.package_output_dir)
    except SyncWorkflowError as exc:
        raise _sync_error(chart, workspace, STAGE_PACKAGE, exc.message) from None

    try:
        push_result = run_helm_push(
            command_runner,
            packaged_chart,
            chart.output_chart_ref,
        )
    except ValueError as exc:
        raise _sync_error(chart, workspace, STAGE_OCI_PUSH, str(exc)) from None
    _write_command_logs(workspace.logs_dir, "helm-push", push_result)
    if push_result.returncode != 0:
        raise _sync_error(
            chart,
            workspace,
            STAGE_OCI_PUSH,
            _format_command_failure("helm push failed", push_result),
        )

    return SyncResult(
        source_repo=chart.source_repo,
        source_chart=chart.source_chart,
        source_version=chart.source_version,
        patch_file=chart.patch_file,
        registry_url=chart.registry_url,
        output_chart_ref=chart.output_chart_ref,
        workspace_path=workspace.root,
        chart_archive_path=chart_archive,
        unpacked_chart_path=unpacked_chart,
        original_render_path=workspace.original_render_path,
        patched_render_path=workspace.patched_render_path,
        discovered_images=discovered_images,
        final_rendered_images=final_rendered_images,
        image_target_mappings=image_target_mappings,
        mirrored_images=mirrored_images,
        applied_patch_file=applied_patch.patch_file,
        image_rewrites=rewrite_result.mappings,
        rewritten_files=tuple(change.path for change in rewrite_result.changes),
        rewrite_replacements=rewrite_result.total_replacements,
        final_helm_lint_verified=final_helm_lint_verified,
        final_helm_template_verified=final_helm_template_verified,
        packaged_chart_path=packaged_chart,
        pushed_chart_ref=chart.output_chart_ref,
    )


def create_sync_workspace(
    chart: NormalizedChartConfig,
    *,
    repo_root: Path,
) -> SyncWorkspace:
    tmp_root = repo_root / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    root = Path(tempfile.mkdtemp(prefix="chartpatch-sync-", dir=tmp_root))
    download_dir = root / "downloaded"
    unpacked_root = root / "unpacked"
    render_dir = root / "rendered"
    package_output_dir = root / "packages"
    logs_dir = root / "logs"

    for path in (download_dir, unpacked_root, render_dir, package_output_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    chart_dir_name = _source_chart_dir_name(chart.source_chart)
    return SyncWorkspace(
        root=root,
        download_dir=download_dir,
        expected_archive_path=download_dir
        / f"{chart_dir_name}-{chart.source_version}.tgz",
        unpacked_root=unpacked_root,
        expected_chart_dir=unpacked_root / chart_dir_name,
        original_render_path=render_dir / "original.yaml",
        patched_render_path=render_dir / "patched.yaml",
        package_output_dir=package_output_dir,
        logs_dir=logs_dir,
    )


def render_sync_report(
    result: SyncResult,
    *,
    chart_name: str | None = None,
    status: str | None = None,
) -> str:
    lines = [
        "ChartPatch sync report",
    ]
    if chart_name is not None:
        lines.append(f"Configured chart name: {chart_name}")
    if status is not None:
        lines.append(f"Sync status: {status}")
    lines.extend(
        [
            f"Source chart repo: {result.source_repo}",
            f"Source chart name: {result.source_chart}",
            f"Source chart version: {result.source_version}",
            f"Configured patch file: {result.patch_file}",
            f"Local registry URL: {result.registry_url}",
            f"Output OCI chart reference: {result.output_chart_ref}",
            f"Workspace path: {result.workspace_path}",
            f"Pulled chart archive: {result.chart_archive_path}",
            f"Unpacked chart path: {result.unpacked_chart_path}",
            f"Original render output: {result.original_render_path}",
            f"Discovered images: {len(result.discovered_images)}",
        ]
    )
    lines.extend(f"  - {image}" for image in sorted(result.discovered_images))
    if result.image_target_mappings:
        lines.append(f"Image target mappings: {len(result.image_target_mappings)}")
        lines.extend(
            f"  - {mapping.source} -> {mapping.target}"
            for mapping in sorted(
                result.image_target_mappings,
                key=lambda mapping: (mapping.source, mapping.target),
            )
        )
    lines.append("Image mirroring summary:")
    if result.mirrored_images:
        lines.append(f"  Mirrored images: {len(result.mirrored_images)}")
        lines.extend(
            f"  - {image.source} -> {image.target}: passed"
            for image in sorted(
                result.mirrored_images,
                key=lambda image: (image.source, image.target),
            )
        )
    else:
        lines.append("  Mirrored images: 0")
    if result.applied_patch_file is not None:
        lines.append("Patch application status: passed")
        lines.append(f"Applied patch: {result.applied_patch_file}")
    else:
        lines.append("Patch application status: skipped")
    if result.image_rewrites:
        lines.append(f"Image rewrites: {len(result.image_rewrites)}")
        lines.extend(
            "  - "
            f"{rewrite.source} -> {rewrite.target} "
            f"({rewrite.replacements} replacements)"
            for rewrite in sorted(
                result.image_rewrites,
                key=lambda rewrite: (rewrite.source, rewrite.target),
            )
        )
    if result.rewrite_replacements or result.rewritten_files:
        lines.append(f"Image rewrite replacements: {result.rewrite_replacements}")
        lines.extend(f"  - {path}" for path in sorted(result.rewritten_files, key=str))
    if result.patched_render_path is not None:
        lines.append(f"Patched render output: {result.patched_render_path}")
        lines.append("Image rewrite verification status: passed")
        lines.append(f"Final rendered images: {len(result.final_rendered_images)}")
        lines.extend(f"  - {image}" for image in sorted(result.final_rendered_images))
    else:
        lines.append("Image rewrite verification status: skipped")
    lines.append(
        "Final helm lint verification: "
        f"{_verification_status(result.final_helm_lint_verified)}"
    )
    lines.append(
        "Final helm template verification: "
        f"{_verification_status(result.final_helm_template_verified)}"
    )
    if result.packaged_chart_path is not None:
        lines.append(f"Packaged chart: {result.packaged_chart_path}")
    if result.pushed_chart_ref is not None:
        lines.append(f"Pushed OCI chart reference: {result.pushed_chart_ref}")
    lines.append("Overall status: success")
    return "\n".join(lines) + "\n"


def render_sync_failure_report(error: SyncWorkflowError) -> str:
    lines = ["ChartPatch sync failed"]
    if error.stage is not None:
        lines.append(f"Failed stage: {error.stage}")
    if error.source_repo is not None:
        lines.append(f"Source chart repo: {error.source_repo}")
    if error.source_chart is not None:
        lines.append(f"Source chart name: {error.source_chart}")
    if error.source_version is not None:
        lines.append(f"Source chart version: {error.source_version}")
    if error.workspace_path is not None:
        lines.append(f"Workspace path: {error.workspace_path}")
    lines.append("Error:")
    lines.append(error.message)
    return "\n".join(lines) + "\n"


def render_chart_sync_report(report: ChartSyncReport) -> str:
    if report.result is not None:
        return render_sync_report(
            report.result,
            chart_name=report.chart_name,
            status="success",
        )

    assert report.error is not None
    lines = [
        "ChartPatch sync failed",
        f"Configured chart name: {report.chart_name}",
        "Sync status: failure",
    ]
    if report.error.stage is not None:
        lines.append(f"Failed stage: {report.error.stage}")
    lines.extend(
        [
            f"Source chart repo: {report.source_repo}",
            f"Source chart name: {report.source_chart}",
            f"Source chart version: {report.source_version}",
            f"Configured patch file: {report.patch_file}",
            f"Local registry URL: {report.registry_url}",
            f"Output OCI chart reference: {report.output_chart_ref}",
        ]
    )
    if report.error.workspace_path is not None:
        lines.append(f"Workspace path: {report.error.workspace_path}")
    lines.append("Error:")
    lines.append(report.error.message)
    return "\n".join(lines) + "\n"


def _verification_status(verified: bool) -> str:
    if verified:
        return "passed"
    return "skipped"


def _sync_error(
    chart: NormalizedChartConfig,
    workspace: SyncWorkspace | None,
    stage: str,
    message: str,
) -> SyncWorkflowError:
    return SyncWorkflowError(
        message,
        stage=stage,
        source_repo=chart.source_repo,
        source_chart=chart.source_chart,
        source_version=chart.source_version,
        workspace_path=workspace.root if workspace is not None else None,
    )


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


def _find_packaged_chart_archive(package_output_dir: Path) -> Path:
    archives = sorted(package_output_dir.glob("*.tgz"))
    if not archives:
        raise SyncWorkflowError(
            f"missing packaged chart archive in {package_output_dir}"
        )
    if len(archives) > 1:
        found = ", ".join(str(path) for path in archives)
        raise SyncWorkflowError(f"ambiguous packaged chart archives: {found}")
    return archives[0]


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
