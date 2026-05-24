# chartpatch

`chartpatch` is an MVP CLI for syncing one pinned upstream Helm chart into a
local unauthenticated OCI registry. It pulls the chart, renders the original
manifests to discover upstream container images, mirrors those images into the
local registry, applies a reusable Git patch, rewrites chart image references to
the local registry, verifies the patched chart, packages it, and pushes the
patched chart as an OCI artifact.

The MVP supports one configured chart per YAML config.

## Prerequisites

Install these tools before running `chartpatch sync`:

- `helm`
- `git`
- `skopeo`
- Docker-compatible runtime for running a local Registry v2 instance

Full local end-to-end validation is opt-in and also requires `kubectl` plus
`k3d`, which starts a local `k3s` cluster for installing the patched chart.

## Local registry

For local development, run an unauthenticated Docker Registry v2 on
`localhost:5000`. The same registry stores mirrored container images and patched
Helm chart OCI artifacts.

```yaml
services:
  registry:
    image: registry:2
    container_name: local-oci-registry
    ports:
      - "5000:5000"
    environment:
      REGISTRY_STORAGE_DELETE_ENABLED: "true"
    volumes:
      - registry-data:/var/lib/registry

volumes:
  registry-data:
```

## Config

Use the MVP single-chart config shape:

```yaml
registry:
  url: localhost:5000

chart:
  name: kube-prometheus-stack
  source:
    repo: https://prometheus-community.github.io/helm-charts
    chart: kube-prometheus-stack
    version: 70.0.0
  patch:
    file: patches/kube-prometheus-stack.patch
  output:
    chart_ref: oci://localhost:5000/helm/kube-prometheus-stack
  verification:
    helm_lint: true
    helm_template: true
```

All fields shown above are required. `verification.helm_lint` and
`verification.helm_template` must be booleans.

## Commands

Print a side-effect-free execution plan:

```bash
chartpatch plan config.yaml
```

`plan` parses and validates the config, then prints the configured source chart,
patch file, local registry target, output OCI chart reference, and verification
steps. It must not mutate remote state, start containers, pull images, apply
patches, or push charts.

Run the sync workflow:

```bash
chartpatch sync config.yaml
```

At a practical workflow level, `sync`:

1. Checks that `helm`, `git`, and `skopeo` are available.
2. Pulls the configured chart version with `helm pull`.
3. Unpacks the chart into a temporary workspace under `tmp/`.
4. Renders the original chart with `helm template`.
5. Discovers container images from the original rendered manifests before any
   patching or image rewriting.
6. Maps each discovered image to a local target shaped as
   `<local-registry>/<normalized-original-reference>`, for example
   `localhost:5000/docker.io/library/nginx:latest` for `nginx:latest`.
7. Mirrors images with `skopeo copy`.
8. Initializes a temporary Git repository in the unpacked chart, creates a
   baseline commit, and applies the configured patch with `git am --reject`.
9. Rewrites image references in chart files to the mapped local registry
   targets.
10. Renders the patched chart and verifies that detected upstream image
    references no longer leak into the final manifests.
11. Runs configured final verification with `helm lint` and/or `helm template`.
12. Packages the patched chart with `helm package`.
13. Pushes the packaged chart to `chart.output.chart_ref` with `helm push`.
14. Prints a run report with the workspace path, discovered images, image
    mappings, patch status, rewrite summary, verification status, package path,
    and pushed OCI chart reference.

`sync` mutates the configured local registry by pushing mirrored images and the
patched chart. The MVP assumes the local registry is unauthenticated.

## End-to-end validation

The Kyverno E2E harness is excluded from default pytest runs. To run it, opt in
with both the environment gate and marker selection:

```bash
CHARTPATCH_RUN_E2E=1 python -m pytest -q -m e2e tests/test_chartpatch_e2e_kyverno.py
```

If Docker or a compatible runtime, local registry support, `k3d`/`k3s`, `helm`,
`skopeo`, required permissions, or upstream network access is unavailable, the
harness reports an explicit skip reason for the failed prerequisite stage.

## Patch creation

Patches are expected to be Git format patches created from chart changes:

```bash
git format-patch <base-sha>
```

During `sync`, `chartpatch` applies the configured patch file inside the
unpacked chart directory with:

```bash
git am --reject <patch-file>
```

`--reject` may leave `.rej` files when a patch does not apply cleanly. The MVP
treats a non-zero `git am`, remaining `.rej` files, or an unfinished
`.git/rebase-apply` state as a patch failure.

## MVP limitations

- One chart per config.
- Unauthenticated local registry only.
- No registry authentication.
- No multiple registries.
- No automatic patch generation.
- No automatic patch conflict resolution.
- No GitHub automation.
- No web UI.
