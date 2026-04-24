#!/usr/bin/env bash
# Stop data worker.
#
# Usage:
#   bash scripts/deployment/data_worker/stop_worker.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../lib/common.sh"

log_info "Stopping data worker..."

if [[ -f /tmp/data_worker.pid ]]; then
  read -r pid < /tmp/data_worker.pid
  if [[ -n "$pid" ]] && ps -p "$pid" > /dev/null 2>&1; then
    kill "$pid" 2>/dev/null && log_info "Killed worker PID $pid" || true
  fi
  rm -f /tmp/data_worker.pid
fi

pkill -f "ds_worker" 2>/dev/null && log_info "Killed remaining ds_worker processes" || true

log_info "Data worker stopped"
