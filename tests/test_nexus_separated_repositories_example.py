from __future__ import annotations

from pathlib import Path

from chartpatch.config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPO_ROOT / "examples/nexus-separated-repositories"


def test_separated_example_uses_native_helm_repository_for_all_charts() -> None:
    config = load_config(EXAMPLE_ROOT / "config.yaml")

    assert len(config.charts) == 9
    assert config.registry.url == "localhost:5000"
    assert {
        chart.output.chart_ref for chart in config.charts
    } == {"http://localhost:8081/repository/helm-hosted"}
    assert all(
        chart.patch.file.startswith(
            "examples/nexus-separated-repositories/patches/"
        )
        for chart in config.charts
    )


def test_separated_example_provisions_and_verifies_both_formats() -> None:
    for relative_path in (
        "README.md",
        "start-nexus.sh",
        "run.sh",
        "verify.sh",
        "verify.py",
        "patches/add-nexus-example-marker.patch",
    ):
        assert (EXAMPLE_ROOT / relative_path).is_file()

    start_script = (EXAMPLE_ROOT / "start-nexus.sh").read_text(encoding="utf-8")
    assert "/repositories/helm/hosted" in start_script
    verifier = (EXAMPLE_ROOT / "verify.py").read_text(encoding="utf-8")
    assert 'fetch_names("helm-hosted")' in verifier
    assert 'fetch_names("docker-hosted")' in verifier
