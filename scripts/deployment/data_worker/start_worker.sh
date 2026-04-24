#!/usr/bin/env bash
# Start data worker.
#
# Usage:
#   bash scripts/deployment/data_worker/start_worker.sh [--config <worker_config.json>]
#
# The worker binary is built during cmake/bazel build phase.
# Default config: ${DS_ROOT}/cli/deploy/conf/worker_config.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../lib/common.sh"

DS_ROOT="${DS_ROOT:-$(cd "${SCRIPT_DIR}/../../../yuanrong-datasystem" && pwd)}"
WORKER_CONFIG="${1:-${DS_ROOT}/cli/deploy/conf/worker_config.json}"

if [[ ! -f "${WORKER_CONFIG}" ]]; then
  log_error "Worker config not found: ${WORKER_CONFIG}"
  exit 1
fi

WORKER_BIN="${DS_ROOT}/build/bin/ds_worker"
if [[ ! -x "${WORKER_BIN}" ]]; then
  WORKER_BIN="${DS_ROOT}/bazel-bin/cli/worker/ds_worker"
fi
if [[ ! -x "${WORKER_BIN}" ]]; then
  log_error "Worker binary not found. Build first: scripts/build/build_cmake.sh"
  exit 1
fi

log_info "Starting data worker..."
log_info "  config: ${WORKER_CONFIG}"

LD_LIBRARY_PATH="${DS_ROOT}/build/lib:${LD_LIBRARY_PATH:-}" \
  "${WORKER_BIN}" --flagfile="${WORKER_CONFIG}" &

WORKER_PID=$!
echo "${WORKER_PID}" > /tmp/data_worker.pid

sleep 2
if ps -p "${WORKER_PID}" > /dev/null 2>&1; then
  log_info "Data worker started (PID ${WORKER_PID})"
else
  log_error "Data worker failed to start"
  exit 1
fi
