# Nexus Multi-Chart Example

This example starts `sonatype/nexus3:3.33.0`, provisions an authenticated
Docker hosted repository on `localhost:5000`, mirrors chart images into it,
patches each chart, and publishes the packaged charts as Helm OCI artifacts.

For the alternative where images stay in Docker storage but chart `.tgz`
packages go to a native Nexus Helm repository, see
[`nexus-separated-repositories`](../nexus-separated-repositories/README.md).

## Included Pins

| Chart | Version | Source |
| --- | --- | --- |
| rabbitmq | 16.0.13 | Bitnami OCI |
| raw | 0.2.5 | Helm incubator |
| gateway-helm | v1.8.0 | Envoy OCI |
| kubed | v0.13.2 | AppsCode |
| karpenter | 1.11.1 | AWS Public ECR |
| aws-load-balancer-controller | 3.4.0 | AWS EKS charts |
| kyverno | 3.8.0 | Kyverno |
| kube-bench | 0.1.16 | Delivery Hero |
| policy-reporter | 3.7.4 | Kyverno policy reporter |

These are the chart/version pairs explicitly pinned in the supplied
configuration fragments. Entries that had no version in those fragments are
not assigned an implicit latest version.

## Run

Build `chartpatch` first:

```bash
python -m PyInstaller --clean --noconfirm chartpatch.spec
```

Run the complete example:

```bash
./examples/nexus-multi-chart/run.sh
```

The local credentials are intentionally fixed for this disposable example:

```text
username: admin
password: chartpatch-nexus-password
```

Nexus endpoints:

```text
UI/API: http://localhost:8081
Docker and Helm OCI: http://localhost:5000
```

Inspect stored components:

```bash
curl -u admin:chartpatch-nexus-password \
  'http://localhost:8081/service/rest/v1/components?repository=docker-hosted'
```

Stop or remove the example:

```bash
docker stop chartpatch-nexus
docker rm chartpatch-nexus
docker volume rm chartpatch-nexus-data
```

The shared patch adds `chartpatch-nexus-example.txt` to every chart. Image
registry changes are performed by `chartpatch` from the images discovered in
each rendered chart.
