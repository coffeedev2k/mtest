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
    assert "/repositories/helm/hosted" in start_script
    verifier = (EXAMPLE_ROOT / "verify.py").read_text(encoding="utf-8")
    assert 'fetch_names("helm-hosted")' in verifier
    assert 'fetch_names("docker-hosted")' in verifier
    run_script = (EXAMPLE_ROOT / "run.sh").read_text(encoding="utf-8")
    assert "nexus-e2e.py\" --mode native" in run_script


def test_shared_nexus_e2e_enforces_local_registry() -> None:
    harness = (REPO_ROOT / "examples/nexus-e2e.py").read_text(encoding="utf-8")
    policy = (
        REPO_ROOT / "examples/nexus-e2e/allow-local-registry.yaml"
    ).read_text(encoding="utf-8")

    assert "--disable=traefik@server:0" in harness
    assert "registry.k8s.io/pause:3.10" in harness
    assert "Kyverno accepted an image outside localhost:5000" in harness
    assert "failureAction: Enforce" in policy
    assert 'image: "localhost:5000/*"' in policy
