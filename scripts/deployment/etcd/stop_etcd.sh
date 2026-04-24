#!/usr/bin/env bash
# Stop all etcd processes (single and cluster).
#
# Usage:
#   bash scripts/deployment/etcd/stop_etcd.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../lib/common.sh"

log_info "Stopping etcd processes..."

# Kill by PID files
for pidfile in /tmp/etcd-single.pid /tmp/etcd-cluster.pids; do
  if [[ -f "$pidfile" ]]; then
    while read -r pid; do
      if [[ -n "$pid" ]] && ps -p "$pid" > /dev/null 2>&1; then
        kill "$pid" 2>/dev/null && log_info "Killed $pid" || true
      fi
    done < "$pidfile"
    rm -f "$pidfile"
  fi
done

# Kill any remaining etcd processes (be conservative: only those we started)
pkill -f "etcd.*--data-dir" 2>/dev/null && log_info "Killed remaining etcd processes" || true

log_info "etcd stopped"
