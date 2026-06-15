#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY = REPO_ROOT / "examples/nexus-e2e/allow-local-registry.yaml"
REGISTRY = "localhost:5000"
USERNAME = "admin"
PASSWORD = "chartpatch-nexus-password"
K3S_IMAGE = os.environ.get("K3S_IMAGE", "rancher/k3s:v1.35.5-k3s1")

CHARTS = (
    ("rabbitmq", "rabbitmq", "16.0.13", ()),
    ("raw", "raw", "0.2.5", ()),
    ("envoy-gateway", "gateway-helm", "v1.8.0", ()),
    ("kubed", "kubed", "v0.13.2", ()),
    (
        "karpenter",
        "karpenter",
        "1.11.1",
        ("--set", "replicas=0", "--set", "settings.clusterName=chartpatch-example"),
    ),
    (
        "aws-load-balancer-controller",
        "aws-load-balancer-controller",
        "3.4.0",
        (
            "--set",
            "replicaCount=0",
            "--set",
            "clusterName=chartpatch-example",
            "--set",
            "enableServiceMutatorWebhook=false",
        ),
    ),
    (
        "kube-bench",
        "kube-bench",
        "0.1.16",
        ("--set", "serviceAccount.create=true"),
    ),
    ("policy-reporter", "policy-reporter", "3.7.4", ()),
)
WAIT_RELEASES = {"rabbitmq", "envoy-gateway", "kubed", "policy-reporter"}


def run(
    args: list[str],
    *,
    timeout: int = 600,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    completed = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        input=input_text,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def require_tools() -> None:
    missing = [
        tool
        for tool in ("docker", "helm", "k3d", "kubectl")
        if shutil.which(tool) is None
    ]
    if missing:
        raise RuntimeError("missing required tools: " + ", ".join(missing))


def write_registry_config(path: Path) -> None:
    path.write_text(
        f"""mirrors:
  "{REGISTRY}":
    endpoint:
      - "http://host.k3d.internal:5000"
configs:
  "{REGISTRY}":
    auth:
      username: "{USERNAME}"
      password: "{PASSWORD}"
    tls:
      insecure_skip_verify: true
""",
        encoding="utf-8",
    )


def create_cluster(name: str, k3d_registry_config: Path) -> None:
    run(["k3d", "cluster", "delete", name], check=False, timeout=180)
    run(
        [
            "k3d",
            "cluster",
            "create",
            name,
            "--image",
            K3S_IMAGE,
            "--servers",
            "1",
            "--agents",
            "0",
            "--no-lb",
            "--wait",
            "--registry-config",
            str(k3d_registry_config),
            "--k3s-arg",
            "--disable=traefik@server:0",
        ],
        timeout=600,
    )


def chart_ref(mode: str, name: str, chart: str) -> str:
    if mode == "oci":
        return f"oci://{REGISTRY}/helm/{name}/{chart}"
    return f"chartpatch-native/{chart}"


def helm_transport_args(mode: str, helm_registry_config: Path) -> list[str]:
    if mode == "oci":
        return ["--plain-http", "--registry-config", str(helm_registry_config)]
    return []


def configure_helm(mode: str, helm_registry_config: Path) -> None:
    if mode == "oci":
        run(
            [
                "helm",
                "registry",
                "login",
                REGISTRY,
                "--insecure",
                "--username",
                USERNAME,
                "--password-stdin",
                "--registry-config",
                str(helm_registry_config),
            ],
            input_text=PASSWORD,
        )
        return
    run(
        [
            "helm",
            "repo",
            "add",
            "chartpatch-native",
            "http://localhost:8081/repository/helm-hosted",
            "--username",
            USERNAME,
            "--password",
            PASSWORD,
            "--force-update",
        ]
    )
    run(["helm", "repo", "update", "chartpatch-native"])


def pod_images(value: Any) -> list[str]:
    images: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"containers", "initContainers", "ephemeralContainers"}:
                if isinstance(item, list):
                    images.extend(
                        container["image"]
                        for container in item
                        if isinstance(container, dict)
                        and isinstance(container.get("image"), str)
                    )
            else:
                images.extend(pod_images(item))
    elif isinstance(value, list):
        for item in value:
            images.extend(pod_images(item))
    return images


def assert_local_render(
    mode: str,
    name: str,
    chart: str,
    version: str,
    values: tuple[str, ...],
    registry_config: Path,
) -> None:
    completed = run(
        [
            "helm",
            "template",
            f"verify-{name}",
            chart_ref(mode, name, chart),
            "--version",
            version,
            *values,
            *helm_transport_args(mode, registry_config),
        ]
    )
    images: list[str] = []
    for document in yaml.safe_load_all(completed.stdout):
        images.extend(pod_images(document))
    external = sorted({image for image in images if not image.startswith(f"{REGISTRY}/")})
    if external:
        raise RuntimeError(
            f"{name} still renders external images: {', '.join(external)}"
        )
    print(f"{name}: rendered {len(set(images))} local image(s)")


def install_release(
    mode: str,
    name: str,
    chart: str,
    version: str,
    values: tuple[str, ...],
    registry_config: Path,
) -> None:
    namespace = f"migration-{name}"
    args = [
        "helm",
        "upgrade",
        "--install",
        name,
        chart_ref(mode, name, chart),
        "--version",
        version,
        "--namespace",
        namespace,
        "--create-namespace",
        "--timeout",
        "10m",
        *values,
        *helm_transport_args(mode, registry_config),
    ]
    if name in WAIT_RELEASES:
        args.append("--wait")
    run(args, timeout=720)
    run(["helm", "status", name, "--namespace", namespace])


def install_kyverno(mode: str, registry_config: Path) -> None:
    run(
        [
            "helm",
            "upgrade",
            "--install",
            "kyverno",
            chart_ref(mode, "kyverno", "kyverno"),
            "--version",
            "3.8.1",
            "--namespace",
            "kyverno",
            "--create-namespace",
            "--wait",
            "--timeout",
            "20m",
            "--set",
            "backgroundController.enabled=false",
            "--set",
            "cleanupController.enabled=false",
            "--set",
            "reportsController.enabled=false",
            *helm_transport_args(mode, registry_config),
        ],
        timeout=1320,
    )
    run(
        [
            "kubectl",
            "wait",
            "--for=condition=Available",
            "deployment",
            "--all",
            "--namespace",
            "kyverno",
            "--timeout=300s",
        ],
        timeout=360,
    )


def enforce_policy() -> None:
    run(["kubectl", "apply", "-f", str(POLICY)])
    run(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "clusterpolicy/allow-local-registry-only",
            "--timeout=180s",
        ],
        timeout=240,
    )
    rejected = run(
        [
            "kubectl",
            "run",
            "external-image-must-fail",
            "--image=registry.k8s.io/pause:3.10",
            "--restart=Never",
        ],
        check=False,
    )
    if rejected.returncode == 0:
        raise RuntimeError("Kyverno accepted an image outside localhost:5000")
    output = rejected.stdout + rejected.stderr
    if "allow-local-registry-only" not in output:
        raise RuntimeError("external image failed for a reason unrelated to Kyverno")
    print("Kyverno rejected the external registry as expected.")


def assert_cluster_pods_are_local() -> None:
    completed = run(
        [
            "kubectl",
            "get",
            "pods",
            "--all-namespaces",
            "-o",
            "json",
        ]
    )
    payload = yaml.safe_load(completed.stdout)
    external: list[str] = []
    for pod in payload.get("items", []):
        namespace = pod.get("metadata", {}).get("namespace", "")
        if namespace in {"kube-system", "kube-public", "kube-node-lease"}:
            continue
        for image in pod_images(pod):
            if not image.startswith(f"{REGISTRY}/"):
                external.append(f"{namespace}/{pod['metadata']['name']}: {image}")
    if external:
        raise RuntimeError("non-local workload images found:\n" + "\n".join(external))


def diagnostics() -> None:
    for args in (
        ["kubectl", "get", "pods", "--all-namespaces", "-o", "wide"],
        ["kubectl", "get", "events", "--all-namespaces", "--sort-by=.lastTimestamp"],
    ):
        completed = run(args, check=False)
        if completed.stdout:
            print(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("oci", "native"), required=True)
    args = parser.parse_args()
    require_tools()
    cluster = f"chartpatch-nexus-{args.mode}"

    with tempfile.TemporaryDirectory(prefix="chartpatch-nexus-e2e-") as temp_dir:
        k3d_registry_config = Path(temp_dir) / "registries.yaml"
        helm_registry_config = Path(temp_dir) / "helm-registry.json"
        write_registry_config(k3d_registry_config)
        try:
            create_cluster(cluster, k3d_registry_config)
            configure_helm(args.mode, helm_registry_config)
            assert_local_render(
                args.mode,
                "kyverno",
                "kyverno",
                "3.8.1",
                (),
                helm_registry_config,
            )
            install_kyverno(args.mode, helm_registry_config)
            enforce_policy()
            for name, chart, version, values in CHARTS:
                assert_local_render(
                    args.mode,
                    name,
                    chart,
                    version,
                    values,
                    helm_registry_config,
                )
                install_release(
                    args.mode,
                    name,
                    chart,
                    version,
                    values,
                    helm_registry_config,
                )
            assert_cluster_pods_are_local()
            print(
                f"Nexus {args.mode} migration E2E passed: all charts and "
                "workload images came from local repositories."
            )
            return 0
        except Exception as exc:
            print(f"E2E failed: {exc}", file=sys.stderr)
            diagnostics()
            return 1
        finally:
            if os.environ.get("KEEP_K3D_CLUSTER") != "1":
                run(["k3d", "cluster", "delete", cluster], check=False, timeout=180)
            else:
                print(f"Keeping k3d cluster {cluster} for inspection.")


if __name__ == "__main__":
    raise SystemExit(main())
