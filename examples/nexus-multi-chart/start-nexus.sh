#!/usr/bin/env bash
set -euo pipefail

NEXUS_IMAGE="${NEXUS_IMAGE:-sonatype/nexus3:3.33.0}"
NEXUS_CONTAINER="${NEXUS_CONTAINER:-chartpatch-nexus}"
NEXUS_PASSWORD="${NEXUS_PASSWORD:-chartpatch-nexus-password}"
NEXUS_URL="${NEXUS_URL:-http://localhost:8081}"
REGISTRY_PORT="${REGISTRY_PORT:-5000}"
STATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.state"

mkdir -p "$STATE_DIR"

if docker container inspect "$NEXUS_CONTAINER" >/dev/null 2>&1; then
  docker start "$NEXUS_CONTAINER" >/dev/null
else
  docker run -d \
    --name "$NEXUS_CONTAINER" \
    -p 8081:8081 \
    -p "${REGISTRY_PORT}:5000" \
    -v chartpatch-nexus-data:/nexus-data \
    "$NEXUS_IMAGE" >/dev/null
fi

printf 'Waiting for Nexus %s' "$NEXUS_IMAGE"
for _ in $(seq 1 180); do
  if curl -fsS "$NEXUS_URL/service/rest/v1/status" >/dev/null 2>&1; then
    printf ' ready\n'
    break
  fi
  printf '.'
  sleep 2
done

if ! curl -fsS "$NEXUS_URL/service/rest/v1/status" >/dev/null; then
  echo "Nexus did not become ready" >&2
  exit 1
fi

if curl -fsS -u "admin:$NEXUS_PASSWORD" \
  "$NEXUS_URL/service/rest/v1/security/realms/active" >/dev/null 2>&1; then
  ADMIN_PASSWORD="$NEXUS_PASSWORD"
else
  ADMIN_PASSWORD="$(docker exec "$NEXUS_CONTAINER" cat /nexus-data/admin.password)"
  curl -fsS -u "admin:$ADMIN_PASSWORD" \
    -X PUT \
    -H 'Content-Type: text/plain' \
    --data-binary "$NEXUS_PASSWORD" \
    "$NEXUS_URL/service/rest/v1/security/users/admin/change-password"
  ADMIN_PASSWORD="$NEXUS_PASSWORD"
fi

curl -fsS -u "admin:$ADMIN_PASSWORD" \
  -X PUT \
  -H 'Content-Type: application/json' \
  --data-binary '["NexusAuthenticatingRealm","NexusAuthorizingRealm","DockerToken"]' \
  "$NEXUS_URL/service/rest/v1/security/realms/active"

if ! curl -fsS -u "admin:$ADMIN_PASSWORD" \
  "$NEXUS_URL/service/rest/v1/repositories/docker/hosted/docker-hosted" \
  >/dev/null 2>&1; then
  curl -fsS -u "admin:$ADMIN_PASSWORD" \
    -X POST \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "$NEXUS_URL/service/rest/v1/repositories/docker/hosted" <<JSON
{
  "name": "docker-hosted",
  "online": true,
  "storage": {
    "blobStoreName": "default",
    "strictContentTypeValidation": true,
    "writePolicy": "ALLOW"
  },
  "docker": {
    "v1Enabled": false,
    "forceBasicAuth": true,
    "httpPort": 5000
  }
}
JSON
fi

printf '%s\n' "$ADMIN_PASSWORD" > "$STATE_DIR/admin.password"
chmod 600 "$STATE_DIR/admin.password"

echo "Nexus UI: $NEXUS_URL"
echo "Docker/Helm OCI registry: localhost:$REGISTRY_PORT"
