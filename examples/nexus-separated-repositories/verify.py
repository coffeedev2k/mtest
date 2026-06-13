from __future__ import annotations

import base64
import json
import os
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NEXUS_URL = os.environ.get("NEXUS_URL", "http://localhost:8081")
NEXUS_PASSWORD = os.environ.get(
    "NEXUS_PASSWORD",
    "chartpatch-nexus-password",
)
EXPECTED_CHARTS = {
    "rabbitmq",
    "raw",
    "gateway-helm",
    "kubed",
    "karpenter",
    "aws-load-balancer-controller",
    "kyverno",
    "kube-bench",
    "policy-reporter",
}
EXPECTED_IMAGES = {
    "docker.io/bitnami/rabbitmq",
    "docker.io/envoyproxy/gateway",
    "docker.io/appscode/kubed",
    "public.ecr.aws/karpenter/controller",
    "public.ecr.aws/eks/aws-load-balancer-controller",
    "ghcr.io/kyverno/readiness-checker",
    "reg.kyverno.io/kyverno/background-controller",
    "reg.kyverno.io/kyverno/cleanup-controller",
    "reg.kyverno.io/kyverno/kyverno",
    "reg.kyverno.io/kyverno/kyverno-cli",
    "reg.kyverno.io/kyverno/kyvernopre",
    "reg.kyverno.io/kyverno/reports-controller",
    "docker.io/aquasec/kube-bench",
    "ghcr.io/kyverno/policy-reporter",
}


def fetch_names(repository: str) -> set[str]:
    token: str | None = None
    names: set[str] = set()
    authorization = base64.b64encode(
        f"admin:{NEXUS_PASSWORD}".encode("utf-8")
    ).decode("ascii")
    while True:
        query = {"repository": repository}
        if token is not None:
            query["continuationToken"] = token
        request = Request(
            f"{NEXUS_URL}/service/rest/v1/components?{urlencode(query)}",
            headers={"Authorization": f"Basic {authorization}"},
        )
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        names.update(
            item["name"]
            for item in payload.get("items", ())
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
        token = payload.get("continuationToken")
        if not token:
            return names


def main() -> int:
    chart_names = fetch_names("helm-hosted")
    image_names = fetch_names("docker-hosted")
    missing_charts = sorted(EXPECTED_CHARTS - chart_names)
    missing_images = sorted(EXPECTED_IMAGES - image_names)
    if missing_charts:
        print(
            "Missing native Helm charts: " + ", ".join(missing_charts),
            file=sys.stderr,
        )
    if missing_images:
        print(
            "Missing Docker images: " + ", ".join(missing_images),
            file=sys.stderr,
        )
    if missing_charts or missing_images:
        return 1
    print("Native Helm charts and Docker images are present in separate repositories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
