# Helm Patch Syncer

## Goal

Build a CLI tool that downloads one Helm chart version from an upstream Helm repository, renders the original chart to find upstream container images, mirrors those images into a local OCI registry, applies a reusable patch, rewrites chart image references to the local registry, verifies the patched chart, and pushes the patched chart to the same local OCI registry.

The tool is inspired by `bitnami/charts-syncer`, but its main difference is patch reuse: when a new upstream chart version appears, the same patch can be applied to the new version if the chart structure remains compatible.

## MVP Scope

The first version supports one chart configured in YAML.

The next version may support several chart entries in the same config.

## Local Registry

For local development, the system uses an unauthenticated Docker Registry v2 instance:

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

The local registry stores both:

- mirrored container images
- patched Helm chart OCI artifacts

## Example Config

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

## Workflow

1. Read the YAML config.
2. Download the configured upstream Helm chart version.
3. Unpack the chart into a temporary working directory.
4. Render the original chart with `helm template`.
5. Detect all upstream container images from the rendered Kubernetes manifests.
6. Mirror the detected images to the local OCI registry with `skopeo`.
7. Initialize a temporary Git repository inside the unpacked chart directory.
8. Apply the configured patch with `git apply`.
9. Rewrite chart image references so rendered manifests point to the local registry.
10. Render the patched chart and verify that image references now point to the local registry.
11. Run chart verification:
    - `helm lint`
    - `helm template`
12. Package the patched chart.
13. Push the patched chart to the local OCI registry.
14. Print a run report.

## Image Rewriting

The key transformation is:

```text
original image reference -> localhost:5000/<normalized image reference>
```

Example:

```text
docker.io/bitnami/nginx:1.27.4 -> localhost:5000/docker.io/bitnami/nginx:1.27.4
quay.io/prometheus/prometheus:v3.0.1 -> localhost:5000/quay.io/prometheus/prometheus:v3.0.1
```

Image discovery must happen before the patch/rewrite phase, otherwise the tool may lose the original upstream image references needed for `skopeo copy`.

The MVP may implement image rewriting by changing values in the unpacked chart before final packaging.

## Verification

The MVP should verify that:

- the upstream chart can be downloaded
- the original chart renders successfully
- upstream images are detected before patching
- every detected upstream image has a deterministic local target reference
- all detected images have a target local registry reference
- image mirroring succeeds with `skopeo`
- the patch applies cleanly
- the patched chart renders successfully
- the final rendered manifests reference `localhost:5000`
- `helm lint` passes
- the patched chart can be packaged and pushed as an OCI artifact

## E2E Test Scenario

The main end-to-end test should use a real chart and a local Kubernetes cluster:

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update
helm install kyverno kyverno/kyverno -n kyverno --create-namespace
```

The automated E2E flow should:

1. Start a local unauthenticated OCI registry.
2. Start or reuse a local `k3s` cluster configured to pull from that registry.
3. Download a pinned Kyverno chart version.
4. Render the original chart.
5. Detect all upstream images from the original rendered manifests.
6. Mirror those images to the local registry with `skopeo`.
7. Apply the configured chart patch.
8. Rewrite chart image references to the local registry.
9. Package and push the patched chart to the local registry.
10. Install the patched chart from the local registry into local `k3s`.
11. Verify that the release becomes healthy and that running pods use local image references.

## CLI Shape

Initial commands:

```bash
chartpatch plan config.yaml
chartpatch sync config.yaml
```

`plan` prints what would happen without changing remote state.

`sync` performs the full workflow.

## First Microfeature

Implement:

```bash
chartpatch plan config.yaml
```

It should:

- parse the YAML config
- validate required fields
- print the source chart
- print the patch file
- print the local registry target
- print the verification steps
- exit with a non-zero code for invalid config

## Out Of Scope For MVP

- GitHub PR automation
- registry authentication
- multiple registries
- complex patch conflict resolution
- automatic patch generation
- multi-chart execution
- web UI
