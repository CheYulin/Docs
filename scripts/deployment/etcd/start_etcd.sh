#!/usr/bin/env bash
# Start a single-node etcd for local development.
#
# Usage:
#   bash scripts/deployment/etcd/start_etcd.sh [--data-dir <path>]
#
# Requires: etcd binary on PATH (install via bootstrap or system package manager)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../lib/common.sh"

DATA_DIR="${ETCD_DATA_DIR:-/tmp/etcd-test}"
PORT="${ETCD_PORT:-2379}"
LISTEN_PEER_URL="${ETCD_LISTEN_PEER_URL:-http://0.0.0.0:2380}"
LISTEN_CLIENT_URL="${ETCD_LISTEN_CLIENT_URL:-http://0.0.0.0:${PORT}}"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deployment/etcd/start_etcd.sh [--data-dir <path>]

Options:
  --data-dir <path>   Data directory (default: /tmp/etcd-test)
  --port <port>       Client port (default: 2379)

Requires: etcd binary on PATH
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if ! cmd_exists etcd; then
  log_error "etcd not found on PATH. Install with: scripts/deployment/etcd/install_etcd.sh"
  exit 1
fi

# Stop any existing etcd on this port
pkill -f "etcd.*--data-dir ${DATA_DIR}" 2>/dev/null || true
sleep 1

log_info "Starting etcd single node..."
log_info "  data-dir: ${DATA_DIR}"
log_info "  port: ${PORT}"

mkdir -p "${DATA_DIR}"

etcd \
  --data-dir="${DATA_DIR}" \
  --name=etcd-single \
  --listen-peer-urls="${LISTEN_PEER_URL}" \
  --listen-client-urls="${LISTEN_CLIENT_URL}" \
  --advertise-client-urls="http://127.0.0.1:${PORT}" \
  --initial-cluster-state=new \
  --initial-cluster-token=etcd-single-token &

ETCD_PID=$!
echo "${ETCD_PID}" > /tmp/etcd-single.pid

sleep 2
if ps -p "${ETCD_PID}" > /dev/null 2>&1; then
  log_info "etcd started (PID ${ETCD_PID})"
  if cmd_exists etcdctl; then
    etcdctl endpoint health --endpoints="http://127.0.0.1:${PORT}" && log_info "etcd healthy" || log_error "etcd unhealthy"
  fi
else
  log_error "etcd failed to start"
  exit 1
fi
