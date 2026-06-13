#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXAMPLE_DIR="$REPO_ROOT/examples/nexus-multi-chart"
CHARTPATCH_BIN="${CHARTPATCH_BIN:-$REPO_ROOT/dist/chartpatch}"

"$EXAMPLE_DIR/start-nexus.sh"
"$CHARTPATCH_BIN" plan "$EXAMPLE_DIR/config.yaml"
"$CHARTPATCH_BIN" sync "$EXAMPLE_DIR/config.yaml"
"$EXAMPLE_DIR/verify.sh"
