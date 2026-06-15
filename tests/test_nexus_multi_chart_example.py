from __future__ import annotations

from pathlib import Path

from chartpatch.config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "examples/nexus-multi-chart"


def test_nexus_example_contains_all_explicitly_pinned_charts() -> None:
    config = load_config(EXAMPLE_ROOT / "config.yaml")

    assert config.registry.url == "localhost:5000"
    assert config.registry.username == "admin"
    assert config.registry.password == "chartpatch-nexus-password"
    assert {
        (chart.source.chart, chart.source.version)
        for chart in config.charts
    } == {
        ("rabbitmq", "16.0.13"),
        ("raw", "0.2.5"),
        ("gateway-helm", "v1.8.0"),
        ("kubed", "v0.13.2"),
        ("karpenter", "1.11.1"),
        ("aws-load-balancer-controller", "3.4.0"),
        ("kyverno", "3.8.1"),
        ("kube-bench", "0.1.16"),
        ("policy-reporter", "3.7.4"),
    }
    assert all(
        chart.output.chart_ref.startswith("oci://localhost:5000/")
        for chart in config.charts
    )
    values_by_chart = {
        chart.name: dict(chart.values)
        for chart in config.charts
        if chart.values
    }
    assert values_by_chart == {
        "karpenter": {"settings.clusterName": "chartpatch-example"},
        "aws-load-balancer-controller": {"clusterName": "chartpatch-example"},
    }
    overrides_by_chart = {
        chart.name: dict(chart.image_overrides)
        for chart in config.charts
        if chart.image_overrides
    }
    assert overrides_by_chart == {
        "rabbitmq": {
            "docker.io/bitnami/rabbitmq:4.1.3-debian-12-r1": (
                "docker.io/bitnamilegacy/rabbitmq:4.1.3-debian-12-r1"
            )
        },
        "kubed": {
            "appscode/kubed:v0.13.2": (
                "docker.io/rancher/mirrored-appscode-kubed:v0.13.2"
            )
        },
    }


def test_nexus_example_scripts_and_per_chart_patches_are_present() -> None:
    for relative_path in (
        "README.md",
        "start-nexus.sh",
        "run.sh",
        "verify.sh",
        "verify.py",
    ):
        assert (EXAMPLE_ROOT / relative_path).is_file()

    config = load_config(EXAMPLE_ROOT / "config.yaml")
    patch_files = {chart.patch.file for chart in config.charts}
    assert len(patch_files) == len(config.charts) == 9
    for patch_file in patch_files:
        text = (REPO_ROOT / patch_file).read_text(encoding="utf-8")
        assert text.startswith("From ")
        assert "localhost:5000" in text or "migration-smoke" in text

    start_script = (EXAMPLE_ROOT / "start-nexus.sh").read_text(encoding="utf-8")
    assert "sonatype/nexus3:3.33.0" in start_script
    assert '"DockerToken"' in start_script
    assert '"httpPort": 5000' in start_script
    run_script = (EXAMPLE_ROOT / "run.sh").read_text(encoding="utf-8")
    assert "nexus-e2e.py\" --mode oci" in run_script
