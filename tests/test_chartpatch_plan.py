from __future__ import annotations

from chartpatch.config import validate_config
from chartpatch.plan import build_plan, render_plan

VALID_CONFIG = {
    "registry": {"url": "localhost:5000"},
    "chart": {
        "name": "kube-prometheus-stack",
        "source": {
            "repo": "https://prometheus-community.github.io/helm-charts",
            "chart": "kube-prometheus-stack",
            "version": "70.0.0",
        },
        "patch": {"file": "patches/kube-prometheus-stack.patch"},
        "output": {"chart_ref": "oci://localhost:5000/helm/kube-prometheus-stack"},
        "verification": {"helm_lint": True, "helm_template": True},
    },
}

MULTI_CHART_CONFIG = {
    "registry": {"url": "localhost:5000"},
    "charts": [
        VALID_CONFIG["chart"],
        {
            "name": "kyverno",
            "source": {
                "repo": "https://kyverno.github.io/kyverno",
                "chart": "kyverno",
                "version": "3.3.7",
            },
            "patch": {"file": "patches/kyverno.patch"},
            "output": {"chart_ref": "oci://localhost:5000/helm/kyverno"},
            "verification": {"helm_lint": False, "helm_template": True},
        },
    ],
}


def test_rendered_plan_includes_required_valid_config_fields() -> None:
    plan = render_plan(validate_config(VALID_CONFIG))

    assert "Configured chart name: kube-prometheus-stack" in plan
    assert "Source chart repo: https://prometheus-community.github.io/helm-charts" in plan
    assert "Source chart name: kube-prometheus-stack" in plan
    assert "Source chart version: 70.0.0" in plan
    assert "Configured patch file: patches/kube-prometheus-stack.patch" in plan
    assert "Local registry URL: localhost:5000" in plan
    assert "Output OCI chart reference: oci://localhost:5000/helm/kube-prometheus-stack" in plan
    assert "No remote mutation: plan only reads the config and prints this plan." in plan


def test_plan_object_includes_required_valid_config_fields() -> None:
    plan = build_plan(validate_config(VALID_CONFIG))

    assert plan.source_repo == "https://prometheus-community.github.io/helm-charts"
    assert plan.source_chart == "kube-prometheus-stack"
    assert plan.source_version == "70.0.0"
    assert plan.patch_file == "patches/kube-prometheus-stack.patch"
    assert plan.registry_url == "localhost:5000"
    assert plan.output_chart_ref == "oci://localhost:5000/helm/kube-prometheus-stack"
    assert plan.helm_lint is True
    assert plan.helm_template is True


def test_multi_chart_plan_object_preserves_config_order() -> None:
    plan = build_plan(validate_config(MULTI_CHART_CONFIG))

    assert tuple(entry.chart_name for entry in plan.entries) == (
        "kube-prometheus-stack",
        "kyverno",
    )
    assert plan.entries[1].source_repo == "https://kyverno.github.io/kyverno"
    assert plan.entries[1].patch_file == "patches/kyverno.patch"
    assert plan.entries[1].output_chart_ref == "oci://localhost:5000/helm/kyverno"


def test_enabled_verification_steps_are_shown_consistently() -> None:
    plan = render_plan(validate_config(VALID_CONFIG))

    assert "  helm_lint: enabled" in plan
    assert "  helm_template: enabled" in plan


def test_disabled_verification_steps_are_shown_consistently() -> None:
    raw = _with_field(VALID_CONFIG, "chart.verification.helm_lint", False)
    raw = _with_field(raw, "chart.verification.helm_template", False)

    plan = render_plan(validate_config(raw))

    assert "  helm_lint: disabled" in plan
    assert "  helm_template: disabled" in plan


def test_multi_chart_plan_output_includes_labeled_chart_sections_in_order() -> None:
    plan = render_plan(validate_config(MULTI_CHART_CONFIG))

    assert plan == (
        "ChartPatch execution plan\n"
        "Configured charts: 2\n"
        "Chart 1: kube-prometheus-stack\n"
        "  Configured chart name: kube-prometheus-stack\n"
        "  Source chart repo: https://prometheus-community.github.io/helm-charts\n"
        "  Source chart name: kube-prometheus-stack\n"
        "  Source chart version: 70.0.0\n"
        "  Configured patch file: patches/kube-prometheus-stack.patch\n"
        "  Local registry URL: localhost:5000\n"
        "  Output OCI chart reference: oci://localhost:5000/helm/kube-prometheus-stack\n"
        "  Verification steps:\n"
        "    helm_lint: enabled\n"
        "    helm_template: enabled\n"
        "Chart 2: kyverno\n"
        "  Configured chart name: kyverno\n"
        "  Source chart repo: https://kyverno.github.io/kyverno\n"
        "  Source chart name: kyverno\n"
        "  Source chart version: 3.3.7\n"
        "  Configured patch file: patches/kyverno.patch\n"
        "  Local registry URL: localhost:5000\n"
        "  Output OCI chart reference: oci://localhost:5000/helm/kyverno\n"
        "  Verification steps:\n"
        "    helm_lint: disabled\n"
        "    helm_template: enabled\n"
        "No remote mutation: plan only reads the config and prints this plan.\n"
    )


def _with_field(raw: dict[str, object], field: str, value: object) -> dict[str, object]:
    copied = _copy(raw)
    parent = copied
    parts = field.split(".")
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = value
    return copied


def _copy(value: object) -> object:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value
