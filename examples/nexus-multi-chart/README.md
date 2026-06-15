# Nexus OCI Corporate Migration Example

This example emulates moving externally maintained Helm charts and their
images into repositories owned by a company.

`chartpatch` performs the following flow for every pinned chart:

1. Downloads the chart from its upstream repository.
2. Discovers and mirrors its rendered images into the authenticated Nexus
   Docker repository at `localhost:5000`.
3. Applies that chart's dedicated patch from `patches/`. The patch changes the
   chart defaults to the mirrored `localhost:5000/...` image names.
4. Publishes the patched chart as a Helm OCI artifact in the same Nexus Docker
   repository.
5. Creates a k3d cluster without Traefik, installs the patched Kyverno chart
   from Nexus, and enables an admission policy which rejects company workload
   images not starting with `localhost:5000/`. The `kube-system` namespace is
   excluded because its images are supplied by k3s itself.
6. Installs all patched charts from Nexus and fails if rendering, admission,
   image pulling, or a waited workload rollout fails.

The `raw` chart has no image by default. Its dedicated patch adds a ConfigMap,
so the example still proves that the downloaded chart was patched, published,
and installed.

## Repositories

```text
Nexus UI/API:       http://localhost:8081
Docker images:      http://localhost:5000
Helm OCI artifacts: oci://localhost:5000/helm/...
Username:           admin
Password:           chartpatch-nexus-password
```

This variant keeps images and Helm OCI artifacts in `docker-hosted`. The
separate-storage variant is documented in
[`nexus-separated-repositories`](../nexus-separated-repositories/README.md).

## Pinned Charts

| Chart | Version | Patch |
| --- | --- | --- |
| rabbitmq | 16.0.13 | `rabbitmq-local-images.patch` |
| raw | 0.2.5 | `raw-migration-smoke.patch` |
| gateway-helm | v1.8.0 | `envoy-gateway-local-images.patch` |
| kubed | v0.13.2 | `kubed-local-images.patch` |
| karpenter | 1.11.1 | `karpenter-local-images.patch` |
| aws-load-balancer-controller | 3.4.0 | `aws-load-balancer-controller-local-images.patch` |
| kyverno | 3.8.1 | `kyverno-local-images.patch` |
| kube-bench | 0.1.16 | `kube-bench-local-images.patch` |
| policy-reporter | 3.7.4 | `policy-reporter-local-images.patch` |

RabbitMQ and kubed use `image_overrides` because their historical upstream
image names are no longer pullable. Their patched defaults retain the expected
company-side names.

## Run

Build the binary and run the complete migration test:

```bash
python -m PyInstaller --clean --noconfirm chartpatch.spec
./examples/nexus-multi-chart/run.sh
```

Set `KEEP_K3D_CLUSTER=1` to retain `chartpatch-nexus-oci` after the run for
inspection. Otherwise the disposable cluster is deleted automatically.

Karpenter and AWS Load Balancer Controller require AWS APIs and IAM to operate.
The k3d test installs their real chart resources with zero controller replicas
and verifies their local image defaults and Kyverno admission. The AWS service
mutator webhook is disabled because it has no endpoints at zero replicas.
Kyverno's admission controller remains enabled while its background, cleanup,
and reports controllers are disabled in the disposable cluster. The remaining
long-running workloads are installed with Helm rollout waiting enabled.
