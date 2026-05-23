from __future__ import annotations

from dataclasses import dataclass

from .config import ChartPatchConfig


@dataclass(frozen=True)
class Plan:
    chart_name: str
    source_repo: str
    source_chart: str
    source_version: str
    patch_file: str
    registry_url: str
    output_chart_ref: str
    helm_lint: bool
    helm_template: bool


def build_plan(config: ChartPatchConfig) -> Plan:
    return Plan(
        chart_name=config.chart.name,
        source_repo=config.chart.source.repo,
        source_chart=config.chart.source.chart,
        source_version=config.chart.source.version,
        patch_file=config.chart.patch.file,
        registry_url=config.registry.url,
        output_chart_ref=config.chart.output.chart_ref,
        helm_lint=config.chart.verification.helm_lint,
        helm_template=config.chart.verification.helm_template,
    )


def render_plan(config: ChartPatchConfig) -> str:
    from .report import render_plan as render_plan_report

    return render_plan_report(build_plan(config))


def _enabled(value: bool) -> str:
    if value:
        return "enabled"
    return "disabled"
