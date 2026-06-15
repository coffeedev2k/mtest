# Nexus Separate Docker And Helm Repositories

This example runs the same corporate migration and k3d/Kyverno verification as
[`nexus-multi-chart`](../nexus-multi-chart/README.md), but stores artifact
formats in separate Nexus repositories:

```text
docker-hosted -> mirrored container images on localhost:5000
helm-hosted   -> patched chart .tgz files and index.yaml on localhost:8081
```

For every upstream chart, `chartpatch` mirrors its active images, applies that
chart's dedicated patch so the packaged defaults point to
`localhost:5000/...`, and uploads the patched archive to `helm-hosted`.

The E2E then:

1. Creates k3d with Traefik disabled and authenticated access to the Nexus
   Docker repository.
2. Installs the patched Kyverno chart from `helm-hosted`.
3. Enforces a policy that permits only `localhost:5000/*` workload images and
   proves that an external image is rejected. `kube-system` is excluded because
   those images belong to the k3s runtime rather than the migrated charts.
4. Installs all nine patched charts from `helm-hosted`.
5. Fails on an external rendered image, denied admission, image pull failure,
   failed Helm install, or failed waited rollout.

There is one patch per chart in `patches/`, including a ConfigMap patch for the
otherwise empty `raw` chart. The chart/version matrix and AWS controller
limitations are the same as in the OCI sibling example.

## Difference From The OCI Variant

| Variant | Images | Charts | Consumer workflow |
| --- | --- | --- | --- |
| OCI | `docker-hosted` | Helm OCI in `docker-hosted` | `helm pull oci://...` |
| Separate | `docker-hosted` | `.tgz` in `helm-hosted` | `helm repo add` |

The native repository is useful for systems that require `index.yaml`,
traditional Helm URLs, or independent chart permissions and retention.

## Run

```bash
python -m PyInstaller --clean --noconfirm chartpatch.spec
./examples/nexus-separated-repositories/run.sh
```

The native repository can also be inspected directly:

```bash
helm repo add chartpatch-native \
  http://localhost:8081/repository/helm-hosted \
  --username admin \
  --password chartpatch-nexus-password
helm repo update chartpatch-native
helm search repo chartpatch-native
```

Set `KEEP_K3D_CLUSTER=1` to retain `chartpatch-nexus-native`; otherwise the
cluster is deleted after the run.
