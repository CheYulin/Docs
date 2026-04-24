#!/usr/bin/env bash
# Start a 3-node etcd cluster for local development.
#
# Usage:
#   bash scripts/deployment/etcd/start_etcd_cluster.sh
#
# Nodes: 127.0.0.1:23790, 127.0.0.1:23791, 127.0.0.1:23792

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../lib/common.sh"

CLUSTER_DATA_DIR="${CLUSTER_DATA_DIR:-/tmp/etcd-cluster}"
PORTS=(23790 23791 23792)
NAMES=(etcd-0 etcd-1 etcd-2)

usage() {
  cat <<'EOF'
Usage:
  bash scripts/deployment/etcd/start_etcd_cluster.sh [--data-dir <path>]

Options:
  --data-dir <path>   Base data directory (default: /tmp/etcd-cluster)

Requires: etcd binary on PATH
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) CLUSTER_DATA_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if ! cmd_exists etcd; then
  log_error "etcd not found on PATH"
  exit 1
fi

# Stop any existing cluster
pkill -f "etcd.*${CLUSTER_DATA_DIR}" 2>/dev/null || true
sleep 1

mkdir -p "${CLUSTER_DATA_DIR}"

INITIAL_CLUSTER=""
for i in "${!PORTS[@]}"; do
  INITIAL_CLUSTER+="${NAMES[$i]}=http://127.0.0.1:${PORTS[$i]},"

  DATA_DIR="${CLUSTER_DATA_DIR}/node-${i}"
  mkdir -p "${DATA_DIR}"

  etcd \
    --data-dir="${DATA_DIR}" \
    --name="${NAMES[$i]}" \
    --listen-peer-urls="http://0.0.0.0:$((2380 + i))" \
    --listen-client-urls="http://0.0.0.0:${PORTS[$i]}" \
    --advertise-client-urls="http://127.0.0.1:${PORTS[$i]}" \
    --initial-cluster-state=new \
    --initial-cluster-token=etcd-cluster-token \
    --initial-cluster="${INITIAL_CLUSTER%,}" &

  echo $! >> /tmp/etcd-cluster.pids
done

echo "${INITIAL_CLUSTER%,}" > /tmp/etcd-cluster.ini

sleep 3
log_info "etcd cluster started on ports ${PORTS[*]}"

ENDPOINTS="$(IFS=','; echo "${PORTS[*]/%/}"; IFS=' ')"
etcdctl --endpoints="127.0.0.1:23790,127.0.0.1:23791,127.0.0.1:23792" endpoint health 2>&1 | head -5 || log_error "cluster may not be fully ready yet"
