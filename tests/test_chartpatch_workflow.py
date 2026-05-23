from __future__ import annotations

from chartpatch.config import validate_config
from chartpatch.workflow import SYNC_STAGE_NAMES, build_sync_summary, render_sync_summary


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


EXPECTED_SYNC_STAGE_NAMES = (
    "pull chart",
    "render original chart",
    "discover images",
    "mirror images",
    "apply patch",
    "rewrite images",
)


def test_sync_stage_order_is_defined_in_code() -> None:
    assert SYNC_STAGE_NAMES == EXPECTED_SYNC_STAGE_NAMES


def test_build_sync_summary_uses_config_fields() -> None:
    summary = build_sync_summary(validate_config(VALID_CONFIG))

    assert summary.source_repo == "https://prometheus-community.github.io/helm-charts"
    assert summary.source_chart == "kube-prometheus-stack"
    assert summary.source_version == "70.0.0"
    assert summary.patch_file == "patches/kube-prometheus-stack.patch"
    assert summary.registry_url == "localhost:5000"
    assert summary.output_chart_ref == "oci://localhost:5000/helm/kube-prometheus-stack"
    assert summary.stage_names == EXPECTED_SYNC_STAGE_NAMES


def test_render_sync_summary_includes_required_fields_and_ordered_stages() -> None:
    output = render_sync_summary(build_sync_summary(validate_config(VALID_CONFIG)))

    assert "Source chart repo: https://prometheus-community.github.io/helm-charts" in output
    assert "Source chart name: kube-prometheus-stack" in output
    assert "Source chart version: 70.0.0" in output
    assert "Patch file: patches/kube-prometheus-stack.patch" in output
    assert "Local registry URL: localhost:5000" in output
    assert "Output OCI chart reference: oci://localhost:5000/helm/kube-prometheus-stack" in output
    assert "Planned sync stages:\n  1. pull chart\n  2. render original chart" in output
    assert "  6. rewrite images\n" in output
    assert "No remote mutation" in output
