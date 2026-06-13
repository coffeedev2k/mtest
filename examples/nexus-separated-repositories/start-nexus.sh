#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEXUS_URL="${NEXUS_URL:-http://localhost:8081}"
NEXUS_PASSWORD="${NEXUS_PASSWORD:-chartpatch-nexus-password}"

"$SCRIPT_DIR/../nexus-multi-chart/start-nexus.sh"

if ! curl -fsS -u "admin:$NEXUS_PASSWORD" \
  "$NEXUS_URL/service/rest/v1/repositories/helm/hosted/helm-hosted" \
  >/dev/null 2>&1; then
  curl -fsS -u "admin:$NEXUS_PASSWORD" \
    -X POST \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "$NEXUS_URL/service/rest/v1/repositories/helm/hosted" <<JSON
{
  "name": "helm-hosted",
  "online": true,
  "storage": {
    "blobStoreName": "default",
    "strictContentTypeValidation": true,
    "writePolicy": "ALLOW"
  }
}
JSON
fi

echo "Native Helm repository: $NEXUS_URL/repository/helm-hosted"
