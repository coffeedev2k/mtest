# chartpatch Release Readiness Report

Date: 2026-05-24

## Summary

The current checkout satisfies the product brief for the `chartpatch` workflow
based on the repository implementation, README, tests, and completed build
memory. This report records release readiness only; it does not introduce new
CLI behavior or product features.

The product brief's original single-chart MVP is implemented, and the later
multi-chart extension is present. `chartpatch plan CONFIG` remains the
side-effect-free validation and preview command. `chartpatch sync CONFIG`
orchestrates the full chart synchronization workflow against a local
unauthenticated OCI registry.

## Product-Brief Coverage

| Product area | Readiness |
| --- | --- |
| `chartpatch plan` | Satisfied. Config loading and validation support single-chart and multi-chart shapes and print source, patch, registry target, output chart reference, and verification steps. |
| `chartpatch sync` | Satisfied. The command covers dependency checks, chart pull, unpack, original render, image discovery, mirroring, patching, rewrite, verification, package, push, and run reporting. |
| Image discovery and deterministic local mapping | Satisfied. Rendered manifests are inspected before patching, including standard containers, init containers, and ephemeral containers. Images map deterministically to `<registry>/<normalized-original-reference>`. |
| Image mirroring | Satisfied. Sync mirrors discovered upstream images to the configured local registry through `skopeo copy`. |
| Git patch application and failure handling | Satisfied. Patches are applied as Git format patches with `git am --reject`; non-zero apply results, `.rej` leftovers, and unfinished apply state are treated as failures. |
| Image rewriting and verification | Satisfied. Chart files are rewritten so patched renders point at local registry targets, and post-rewrite verification checks for leaked upstream references. |
| Helm lint/template verification | Satisfied. `verification.helm_lint` and `verification.helm_template` control final Helm checks. |
| Chart packaging and OCI push | Satisfied. Patched charts are packaged and pushed to `chart.output.chart_ref` with Helm. |
| Multi-chart support | Satisfied. Configs may use a top-level `charts` list; `plan` and `sync` normalize the shared chart entry shape, process entries in order, report per-chart outcomes, continue after per-chart failures, and return an aggregate failure exit code when needed. |
| Kyverno E2E harness | Present but optional. The repository includes pinned Kyverno fixtures and an opt-in pytest E2E harness gated by `CHARTPATCH_RUN_E2E=1` and the `e2e` marker. |

## Completed Build-Memory Areas

The repository build memory records completed increments for:

- `chartpatch plan config.yaml`.
- `chartpatch sync` skeleton and dependency checks.
- Sync workspace creation, chart pull, unpack, and original render.
- Rendered-manifest image discovery.
- Deterministic image target mapping.
- Image mirroring.
- Git patch application and strict failure handling.
- Patched chart image rewrite.
- Post-rewrite patched render verification.
- Configurable final Helm verification.
- Patched chart packaging and OCI push.
- Final run reporting and failure-stage reporting.
- Regression coverage for patch leftovers and late-stage failures.
- Developer-facing documentation.
- Pinned Kyverno E2E fixtures and opt-in harness.
- Multi-chart `plan` support.
- Shared chart config normalization for `plan` and `sync`.
- Reusable single-chart sync workflow boundary.
- Multi-chart `sync` dispatch and result aggregation.
- Ephemeral container image discovery coverage.
- Multi-chart README updates, validation, fixtures, and CLI regression coverage.
- Fast release-readiness and final product-brief acceptance sweeps.

## Required Fast Test Gate

| Command | Result | Notes |
| --- | --- | --- |
| `python -m pytest -q` | Failed | System Python does not have pytest installed: `No module named pytest`. No product tests ran under this interpreter. |
| `.venv/bin/python -m pytest -q` | Passed | `269 passed, 1 deselected in 9.46s`. The deselected test is the opt-in E2E test excluded by pytest's default `-m "not e2e"` configuration. |

The passing virtualenv command is the effective required fast gate for this
checkout because repository test dependencies are installed there and
`pyproject.toml` configures default pytest runs to exclude E2E.

## Optional Kyverno E2E

The Kyverno E2E harness was not run for this report.

Prerequisite check results:

| Prerequisite command | Result |
| --- | --- |
| `command -v docker` | Found `/usr/bin/docker`. |
| `command -v k3d` | Found `/home/atarasov/.asdf/shims/k3d`. |
| `command -v kubectl` | Found `/home/atarasov/.asdf/shims/kubectl`. |
| `command -v helm` | Found `/home/atarasov/.asdf/shims/helm`. |
| `command -v skopeo` | Not found. |

Skip reason: `skopeo` is unavailable on PATH, so the E2E workflow cannot verify
the required image mirroring phase. Local registry state, k3s readiness, and
network availability were not exercised after this blocking prerequisite was
identified.

To run the opt-in harness when prerequisites are available:

```bash
CHARTPATCH_RUN_E2E=1 .venv/bin/python -m pytest -q -m e2e tests/test_chartpatch_e2e_kyverno.py
```

## Residual Risks

- External tool availability remains required for real `sync` runs: Helm, Git,
  Skopeo, a Docker-compatible runtime, and registry access must be installed and
  usable in the operator environment.
- Network-dependent E2E can fail because upstream Helm repositories, chart
  downloads, image registries, or local network configuration are unavailable or
  slow.
- Upstream chart drift can break reusable patch files even when `chartpatch`
  behaves correctly; pinned versions reduce but do not eliminate that risk.
- Patch conflicts are intentionally handled as stop-the-run failures, not
  automatically resolved.
- Registry and k3s behavior can vary by local runtime, insecure-registry
  configuration, DNS, permissions, and image pull policy.
- Image discovery coverage should continue to be expanded if future Kubernetes
  resources introduce image-bearing fields outside the currently tested paths.
