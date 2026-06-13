# Nexus Separate Docker And Helm Repositories

This variant uses the same `sonatype/nexus3:3.33.0` container as the OCI
example, but stores different artifact formats in separate Nexus repositories:

```text
docker-hosted  -> container images and registry API on localhost:5000
helm-hosted    -> packaged .tgz charts and index.yaml on localhost:8081
```

## Difference From The OCI Variant

The sibling
[`nexus-multi-chart`](../nexus-multi-chart/README.md) example stores both
container images and Helm OCI artifacts in `docker-hosted`. Charts are consumed
with an `oci://localhost:5000/...` reference.

This example uploads chart archives into Nexus's native `helm-hosted`
repository. Consumers use the classic Helm repository workflow:

```bash
helm repo add chartpatch-native \
  http://localhost:8081/repository/helm-hosted \
  --username admin \
  --password chartpatch-nexus-password

helm repo update
helm search repo chartpatch-native
```

The tradeoff is straightforward:

| Variant | Images | Charts | Chart client |
| --- | --- | --- | --- |
| OCI | `docker-hosted` | `docker-hosted` | `helm pull oci://...` |
| Separate | `docker-hosted` | `helm-hosted` | `helm repo add` and `helm pull` |

Use native Helm storage when existing systems expect `index.yaml`, traditional
Helm repository URLs, or separate retention and permissions for charts.

## Run

Build the binary:

```bash
python -m PyInstaller --clean --noconfirm chartpatch.spec
```

Run the complete example:

```bash
./examples/nexus-separated-repositories/run.sh
```

Endpoints and credentials:

```text
Nexus UI/API: http://localhost:8081
Docker registry: http://localhost:5000
Helm repository: http://localhost:8081/repository/helm-hosted
Username: admin
Password: chartpatch-nexus-password
```

The config uses the same nine pinned charts and image overrides as the OCI
example. Only each `output.chart_ref` changes to the native Helm repository
URL.
