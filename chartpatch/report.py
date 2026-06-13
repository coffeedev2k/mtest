from __future__ import annotations

from .plan import ChartPlanEntry, Plan, _enabled


def render_plan(plan: Plan) -> str:
    if len(plan.entries) == 1:
        return _render_single_plan(plan.entries[0])

    lines = [
        "ChartPatch execution plan",
        f"Configured charts: {len(plan.entries)}",
    ]
    for index, entry in enumerate(plan.entries, start=1):
        lines.extend(
            [
                f"Chart {index}: {entry.chart_name}",
                f"  Configured chart name: {entry.chart_name}",
                f"  Source chart repo: {entry.source_repo}",
                f"  Source chart name: {entry.source_chart}",
                f"  Source chart version: {entry.source_version}",
                f"  Configured patch file: {entry.patch_file}",
                f"  Local registry URL: {entry.registry_url}",
                "  Registry authentication: "
                + ("configured" if entry.registry_authenticated else "not configured"),
                f"  Output OCI chart reference: {entry.output_chart_ref}",
                "  Verification steps:",
                f"    helm_lint: {_enabled(entry.helm_lint)}",
                f"    helm_template: {_enabled(entry.helm_template)}",
            ]
        )
    lines.append(
        "No remote mutation: plan only reads the config and prints this plan."
    )
    return "\n".join(lines) + "\n"


def _render_single_plan(entry: ChartPlanEntry) -> str:
    lines = [
        "ChartPatch execution plan",
        f"Configured chart name: {entry.chart_name}",
        f"Source chart repo: {entry.source_repo}",
        f"Source chart name: {entry.source_chart}",
        f"Source chart version: {entry.source_version}",
        f"Configured patch file: {entry.patch_file}",
        f"Local registry URL: {entry.registry_url}",
        "Registry authentication: "
        + ("configured" if entry.registry_authenticated else "not configured"),
        f"Output OCI chart reference: {entry.output_chart_ref}",
        "Verification steps:",
        f"  helm_lint: {_enabled(entry.helm_lint)}",
        f"  helm_template: {_enabled(entry.helm_template)}",
        "No remote mutation: plan only reads the config and prints this plan.",
    ]
    return "\n".join(lines) + "\n"
