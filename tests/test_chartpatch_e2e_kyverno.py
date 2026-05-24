from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from chartpatch.config import load_config
from tests.e2e_support import (
    E2E_ENV_VAR,
    RegistryUnavailable,
    e2e_enabled,
    ensure_local_registry,
    is_localhost_5000_oci_ref,
    missing_required_tools,
    stop_local_registry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
KYVERNO_FIXTURE = REPO_ROOT / "tests/fixtures/chartpatch/e2e/kyverno/config.yaml"
KYVERNO_PATCH = (
    REPO_ROOT
    / "tests/fixtures/chartpatch/e2e/kyverno/patches/use-literal-images.patch"
)


def test_kyverno_e2e_fixture_is_pinned_and_targets_local_registry() -> None:
    config = load_config(KYVERNO_FIXTURE)

    assert config.chart.source.repo == "https://kyverno.github.io/kyverno/"
    assert config.chart.source.chart == "kyverno"
    assert config.chart.source.version == "3.8.1"
    assert config.registry.url == "localhost:5000"
    assert is_localhost_5000_oci_ref(config.chart.output.chart_ref)
    assert config.chart.output.chart_ref == "oci://localhost:5000/helm/kyverno"
    assert config.chart.patch.file == (
        "tests/fixtures/chartpatch/e2e/kyverno/patches/use-literal-images.patch"
    )
    assert KYVERNO_PATCH.read_text(encoding="utf-8").startswith("From ")


@pytest.mark.e2e
def test_chartpatch_sync_kyverno_fixture_through_local_oci_registry() -> None:
    if not e2e_enabled():
        pytest.skip(f"set {E2E_ENV_VAR}=1 to run chartpatch E2E tests")

    missing = missing_required_tools()
    if missing:
        pytest.skip(f"missing E2E dependency: {', '.join(missing)}")

    registry = None
    try:
        registry = ensure_local_registry()
    except RegistryUnavailable as exc:
        pytest.skip(f"missing E2E dependency: {exc}")

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "chartpatch", "sync", str(KYVERNO_FIXTURE)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
    finally:
        if registry is not None:
            stop_local_registry(registry)

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, (
        "chartpatch sync failed\n"
        f"exit code: {completed.returncode}\n"
        f"stdout:\n{completed.stdout}\n"
        f"stderr:\n{completed.stderr}"
    )
    assert "Discovered images:" in output
    assert "Image target mappings:" in output
    assert "localhost:5000/" in output
    assert "Image mirroring summary:" in output
    assert "Mirrored images:" in output
    assert "Patch application status: passed" in output
    assert "Image rewrites:" in output
    assert "Image rewrite verification status: passed" in output
    assert "Packaged chart:" in output
    assert "Pushed OCI chart reference: oci://localhost:5000/helm/kyverno" in output
    assert "Overall status: success" in output
