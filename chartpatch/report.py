from __future__ import annotations

from .plan import Plan, _enabled


def render_plan(plan: Plan) -> str:
    lines = [
        "ChartPatch execution plan",
        f"Configured chart name: {plan.chart_name}",
        f"Source chart repo: {plan.source_repo}",
        f"Source chart name: {plan.source_chart}",
        f"Source chart version: {plan.source_version}",
        f"Configured patch file: {plan.patch_file}",
        f"Local registry URL: {plan.registry_url}",
        f"Output OCI chart reference: {plan.output_chart_ref}",
        "Verification steps:",
        f"  helm_lint: {_enabled(plan.helm_lint)}",
        f"  helm_template: {_enabled(plan.helm_template)}",
        "No remote mutation: plan only reads the config and prints this plan.",
    ]
    return "\n".join(lines) + "\n"
