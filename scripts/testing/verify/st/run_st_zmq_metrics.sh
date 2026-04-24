#!/usr/bin/env bash
# ZMQ metrics ST integration test.
# Replaces the deprecated run_zmq_rpc_metrics_remote.sh.
#
# Usage:
#   bash scripts/testing/verify/st/run_st_zmq_metrics.sh [--backend cmake|bazel] [--skip-build]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"
BUILD_DIR="${DS_ROOT}/build"

BUILD_BACKEND="${BUILD_BACKEND:-cmake}"
SKIP_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend) BUILD_BACKEND="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=1; shift ;;
    *) shift ;;
  esac
done

cd "${DS_ROOT}"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "Building ZMQ metrics ST targets (backend=${BUILD_BACKEND})..."
  bash build.sh -t build -B "${BUILD_DIR}" -b "${BUILD_BACKEND}" -j "${JOBS:-$(nproc)}" 2>&1 | tail -5
fi

echo "Running ZMQ metrics ST..."
ctest --test-dir "${BUILD_DIR}" \
  --output-on-failure \
  -R "ZmqMetrics|ZmqRpc" \
  -j "${JOBS:-$(nproc)}" 2>&1 | tail -30

echo "ZMQ metrics ST done"
