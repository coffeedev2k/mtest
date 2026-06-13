# ChartPatch Quick Run

This example runs the complete `chartpatch` flow for
`kube-prometheus-stack` `70.0.0` using an authenticated local Registry v2.
The registry stores both mirrored container images and the patched Helm OCI
chart.

## Requirements

Use direct, standard commands. The project intentionally does not use Make.

Required tools:

- Python 3.12 or newer
- Docker
- Helm
- Git
- Skopeo
- k3d and kubectl for cluster validation

## Build

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm chartpatch.spec
./dist/chartpatch --help
```

To expose the development build locally without copying it after every build:

```bash
mkdir -p "$HOME/bin"
ln -sfn "$PWD/dist/chartpatch" "$HOME/bin/chartpatch"
```

`$HOME/bin` must be present in `PATH`.

## Configuration

[`config.yaml`](config.yaml) declares:

- authenticated registry `localhost:5000`;
- source chart `kube-prometheus-stack` `70.0.0`;
- reusable Git patch
  `quickrun/patches/add-quickrun-annotation.patch`;
- local image namespace `localhost:5000/<original-image>`;
- output chart
  `oci://localhost:5000/helm/kube-prometheus-stack`.

The example credentials are only for local development:

```text
username: chartpatch
password: chartpatch-local-password
```

## Run

Show the side-effect-free plan:

```bash
chartpatch plan quickrun/config.yaml
```

Start the authenticated Registry v2 and run the complete sync:

```bash
chartpatch quickrun quickrun/config.yaml
```

The command performs the following flow:

```text
config.yaml
  -> pull kube-prometheus-stack 70.0.0
  -> render and discover all images
  -> authenticate and mirror images to localhost:5000
  -> apply the configured Git patch
  -> rewrite image registries to localhost:5000
  -> lint and render the patched chart
  -> package the chart
  -> authenticate Helm and push the OCI chart
```

## Cluster Validation

The automated Kyverno E2E test exercises the same authenticated registry
contract, including a k3d cluster, local image pulls, and admission checks:

```bash
CHARTPATCH_RUN_E2E=1 \
  python -m pytest -q -m e2e tests/test_chartpatch_e2e_kyverno.py
```

The k3d server is created without Traefik:

```text
--k3s-arg --disable=traefik@server:0
```

To validate the published `kube-prometheus-stack` chart manually, create
`/tmp/chartpatch-registries.yaml`:

```yaml
mirrors:
  "localhost:5000":
    endpoint:
      - "http://host.k3d.internal:5000"
configs:
  "localhost:5000":
    auth:
      username: "chartpatch"
      password: "chartpatch-local-password"
  "host.k3d.internal:5000":
    auth:
      username: "chartpatch"
      password: "chartpatch-local-password"
```

Create the cluster without Traefik:

```bash
k3d cluster create chartpatch-quickrun \
  --image rancher/k3s:v1.35.5-k3s1 \
  --no-lb \
  --k3s-arg=--disable=traefik@server:0 \
  --registry-config /tmp/chartpatch-registries.yaml \
  --wait
```

Then login with Helm and install the chart:

```bash
printf '%s\n' 'chartpatch-local-password' |
  helm registry login localhost:5000 \
    --insecure \
    --username chartpatch \
    --password-stdin

helm install monitoring \
  oci://localhost:5000/helm/kube-prometheus-stack/kube-prometheus-stack \
  --version 70.0.0 \
  --plain-http \
  --namespace monitoring \
  --create-namespace \
  --wait
```

Verify that running workloads use only the local registry:

```bash
kubectl get pods -n monitoring -o json |
  python -c '
import json, sys
data = json.load(sys.stdin)
images = sorted({
    container["image"]
    for pod in data["items"]
    for field in ("initContainers", "containers")
    for container in pod["spec"].get(field, [])
})
print("\n".join(images))
assert images and all(image.startswith("localhost:5000/") for image in images)
'
```

Any failed image pull, Helm install, or rollout must be treated as a failed
validation.
