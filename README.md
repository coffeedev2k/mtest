# chartpatch

`chartpatch` is an MVP CLI for syncing pinned upstream Helm charts into a local
unauthenticated OCI registry. It pulls each chart, renders the original
manifests to discover upstream container images, mirrors those images into the
local registry, applies a reusable Git patch, rewrites chart image references to
the local registry, verifies the patched chart, packages it, and pushes the
patched chart as an OCI artifact.

The CLI accepts both single-chart configs with a top-level `chart` mapping and
multi-chart configs with a top-level `charts` list. `chartpatch plan CONFIG` and
`chartpatch sync CONFIG` both normalize either shape through the same chart
entry fields.

## Binary

The supported distribution is a standalone Linux executable. Build it with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
make binary
./dist/chartpatch --help
```

The build output is `dist/chartpatch`. Copy that file to a directory on `PATH`,
for example:

```bash
sudo install -m 0755 dist/chartpatch /usr/local/bin/chartpatch
```

Python is only needed to build and test the executable. The installed binary
does not require Python or this source tree. It still invokes `helm`, `git`,
`skopeo`, and, for `quickrun`, Docker.

## Quick start

The repository includes a runnable example that adds an annotation to the
pinned Kyverno chart, mirrors its container images, and publishes the changed
chart to a local OCI registry.

Build and run the complete example:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
make quickrun
```

`make quickrun` builds `dist/chartpatch`, starts a persistent Registry v2
container named `chartpatch-registry`, waits until it is ready, and runs:

```bash
./dist/chartpatch quickrun chartpatch.yaml
```

For an already-built or installed binary, put a config and its patch file on
the target system and run:

```bash
chartpatch quickrun /path/to/chartpatch.yaml
```

With no config argument, `quickrun` reads `./chartpatch.yaml`. It downloads
Kyverno `3.8.1`, mirrors its images under `localhost:5000`,
applies the example patch, verifies and packages the changed chart, and pushes
it to the registry. Confirm that the artifacts are present and inspect the
published chart metadata:

```bash
curl -s http://localhost:5000/v2/_catalog | python -m json.tool
helm show chart oci://localhost:5000/helm/kyverno/kyverno --version 3.8.1
```

The Helm output includes the annotation
`chartpatch.dev/quickstart: kyverno-patched`. To stop the persistent registry
while keeping its data, run:

```bash
docker stop chartpatch-registry
```

This workflow requires the external tools listed below and network access to
the upstream chart and image registries.

## Prerequisites

Install these tools before running `chartpatch sync`:

- `helm`
- `git`
- `skopeo`
- Docker for `quickrun` to run the local Registry v2 container

Full local end-to-end validation is opt-in and also requires `kubectl` plus
`k3d`, which starts a local `k3s` cluster for installing the patched chart.

## Local registry

For local development, run an unauthenticated Docker Registry v2 on
`localhost:5000`. The same registry stores mirrored container images and patched
Helm chart OCI artifacts. `quickrun` starts it automatically:

```bash
chartpatch quickrun chartpatch.yaml
```

The equivalent manual Compose definition remains in
`examples/quickstart/compose.yaml`.

```yaml
services:
  registry:
    image: registry:2
    container_name: chartpatch-registry
    restart: unless-stopped
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

Use this single-chart config shape for one chart:

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

For multiple charts, replace top-level `chart` with a non-empty top-level
`charts` list containing entries with the same fields:

```yaml
registry:
  url: localhost:5000

charts:
  - name: kube-prometheus-stack
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
  - name: kyverno
    source:
      repo: https://kyverno.github.io/kyverno
      chart: kyverno
      version: 3.3.7
    patch:
      file: patches/kyverno.patch
    output:
      chart_ref: oci://localhost:5000/helm/kyverno
    verification:
      helm_lint: false
      helm_template: true
```

Configs must specify either `chart` or `charts`, not both. `chartpatch plan` and
`chartpatch sync` support both shapes.

## Commands

Print a side-effect-free execution plan:

```bash
chartpatch plan config.yaml
```

`plan` parses and validates the config, then prints each configured source
chart, patch file, local registry target, output OCI chart reference, and
verification steps. It must not mutate remote state, start containers, pull
images, apply patches, or push charts.

Run the sync workflow:

```bash
chartpatch sync config.yaml
```

Start or reuse a local Docker Registry v2 and then run the sync workflow:

```bash
chartpatch quickrun config.yaml
```

`quickrun` only accepts a registry URL on `localhost` or `127.0.0.1` with an
explicit port. It reuses a reachable registry, starts an existing stopped
`chartpatch-registry` container, or creates one from `registry:2`.

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

For a multi-chart config, `sync` processes chart entries in config order,
prints per-chart results, continues to later charts after a chart failure, and
exits non-zero when any chart fails.

`sync` mutates the configured local registry by pushing mirrored images and the
patched chart. The MVP assumes the local registry is unauthenticated.

## End-to-end validation

The Kyverno E2E harness is excluded from default pytest runs. It remains
opt-in; to run it, use both the environment gate and marker selection:

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

- Unauthenticated local registry only.
- No registry authentication.
- No multiple registries.
- No automatic patch generation.
- No automatic patch conflict resolution.
- No GitHub automation.
- No web UI.
