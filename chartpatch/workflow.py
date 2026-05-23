from __future__ import annotations

from dataclasses import dataclass

from .config import ChartPatchConfig


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
