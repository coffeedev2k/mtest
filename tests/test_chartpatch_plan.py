from __future__ import annotations

from chartpatch.config import validate_config
from chartpatch.plan import render_plan

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


def test_absent_verification_steps_are_shown_consistently() -> None:
    raw = _without_field(VALID_CONFIG, "chart.verification")

    plan = render_plan(validate_config(raw))

    assert "  helm_lint: disabled" in plan
    assert "  helm_template: disabled" in plan


def _without_field(raw: dict[str, object], field: str) -> dict[str, object]:
    copied = _copy(raw)
    parent = copied
    parts = field.split(".")
    for part in parts[:-1]:
        parent = parent[part]
    del parent[parts[-1]]
    return copied


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
    return value
