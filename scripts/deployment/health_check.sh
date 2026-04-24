#!/usr/bin/env bash
# Check health of etcd and data worker.
#
# Usage:
#   bash scripts/deployment/health_check.sh [--etcd-endpoints <url>] [--worker-port <port>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../lib/common.sh"

ETCD_ENDPOINTS="${ETCD_ENDPOINTS:-http://127.0.0.1:2379}"
WORKER_PORT="${WORKER_PORT:-18888}"
WORKER_HOST="${WORKER_HOST:-127.0.0.1}"

check_etcd() {
  if ! cmd_exists etcdctl; then
    log_error "etcdctl not found on PATH"
    return 1
  fi
  if etcdctl --endpoints="${ETCD_ENDPOINTS}" endpoint health > /dev/null 2>&1; then
    log_info "etcd: HEALTHY (${ETCD_ENDPOINTS})"
    return 0
  else
    log_error "etcd: UNHEALTHY (${ETCD_ENDPOINTS})"
    return 1
  fi
}

check_worker() {
  local status
  status=$(curl -s -o /dev/null -w "%{http_code}" "http://${WORKER_HOST}:${WORKER_PORT}/health" 2>/dev/null || echo "000")
  if [[ "$status" == "200" ]]; then
    log_info "data_worker: HEALTHY (${WORKER_HOST}:${WORKER_PORT})"
    return 0
  else
    log_error "data_worker: UNHEALTHY (HTTP ${status}) at ${WORKER_HOST}:${WORKER_PORT}"
    return 1
  fi
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --etcd-endpoints) ETCD_ENDPOINTS="$2"; shift 2 ;;
    --worker-port) WORKER_PORT="$2"; shift 2 ;;
    --worker-host) WORKER_HOST="$2"; shift 2 ;;
    *) shift ;;
  esac
done

banner "Health Check"

failed=0

if ! check_etcd; then ((failed++)); fi
if ! check_worker; then ((failed++)); fi

if [[ "$failed" -eq 0 ]]; then
  log_info "All components healthy"
  exit 0
else
  log_error "$failed component(s) unhealthy"
  exit 1
fi
