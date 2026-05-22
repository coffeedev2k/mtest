from __future__ import annotations

from .config import ChartPatchConfig


def render_plan(config: ChartPatchConfig) -> str:
    verification = config.chart.verification
    lines = [
        "ChartPatch execution plan",
        f"Configured chart name: {config.chart.name}",
        f"Source chart repo: {config.chart.source.repo}",
        f"Source chart name: {config.chart.source.chart}",
        f"Source chart version: {config.chart.source.version}",
        f"Configured patch file: {config.chart.patch.file}",
        f"Local registry URL: {config.registry.url}",
        f"Output OCI chart reference: {config.chart.output.chart_ref}",
        "Verification steps:",
        f"  helm_lint: {_enabled(verification.helm_lint)}",
        f"  helm_template: {_enabled(verification.helm_template)}",
        "No remote mutation: plan only reads the config and prints this plan.",
    ]
    return "\n".join(lines) + "\n"


def _enabled(value: bool) -> str:
    if value:
        return "enabled"
    return "disabled"
