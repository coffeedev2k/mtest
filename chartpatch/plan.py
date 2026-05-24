from __future__ import annotations

from dataclasses import dataclass

from .config import ChartPatchConfig


@dataclass(frozen=True)
class ChartPlanEntry:
    chart_name: str
    source_repo: str
    source_chart: str
    source_version: str
    patch_file: str
    registry_url: str
    output_chart_ref: str
    helm_lint: bool
    helm_template: bool


@dataclass(frozen=True)
class Plan:
    entries: tuple[ChartPlanEntry, ...]

    @property
    def chart_name(self) -> str:
        return self.entries[0].chart_name

    @property
    def source_repo(self) -> str:
        return self.entries[0].source_repo

    @property
    def source_chart(self) -> str:
        return self.entries[0].source_chart

    @property
    def source_version(self) -> str:
        return self.entries[0].source_version

    @property
    def patch_file(self) -> str:
        return self.entries[0].patch_file

    @property
    def registry_url(self) -> str:
        return self.entries[0].registry_url

    @property
    def output_chart_ref(self) -> str:
        return self.entries[0].output_chart_ref

    @property
    def helm_lint(self) -> bool:
        return self.entries[0].helm_lint

    @property
    def helm_template(self) -> bool:
        return self.entries[0].helm_template


def build_plan(config: ChartPatchConfig) -> Plan:
    return Plan(
        entries=tuple(
            ChartPlanEntry(
                chart_name=chart.name,
                source_repo=chart.source.repo,
                source_chart=chart.source.chart,
                source_version=chart.source.version,
                patch_file=chart.patch.file,
                registry_url=config.registry.url,
                output_chart_ref=chart.output.chart_ref,
                helm_lint=chart.verification.helm_lint,
                helm_template=chart.verification.helm_template,
            )
            for chart in config.charts
        )
    )


def render_plan(config: ChartPatchConfig) -> str:
    from .report import render_plan as render_plan_report

    return render_plan_report(build_plan(config))


def _enabled(value: bool) -> str:
    if value:
        return "enabled"
    return "disabled"
