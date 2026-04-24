#!/usr/bin/env bash
# Sync yuanrong-datasystem to hermes agent workspace on a remote node.
# Only syncs datasystem (gitcode, hermes cannot reach gitcode directly).
# The agent-workbench repo is managed by hermes itself via GitHub.
#
# Usage:
#   bash scripts/development/sync/sync_hermes_workspace.sh [--dry-run] [--node <name>]
#
# hermes agent calls this before each task to get latest datasystem code.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"

DRY_RUN=0
NODE_NAME="${NODE_NAME:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run|-n) DRY_RUN=1 ;;
    --node) NODE_NAME="$2"; shift 2 ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${DS_ROOT}" ]]; then
  echo "DATASYSTEM_ROOT not set and ../yuanrong-datasystem not found" >&2
  exit 1
fi

# Load node config
SCRIPT_DIR_FOR_LOAD="${SCRIPT_DIR}" . "${SCRIPT_DIR}/../../lib/load_nodes.sh"
. "${SCRIPT_DIR}/../../lib/common.sh"

NODE="${NODE_NAME:-$(node_default)}"
REMOTE_HOST="$(node_ssh_host "${NODE}")"
REMOTE_USER="$(node_ssh_user "${NODE}")"
REMOTE_HERMES_WS="$(node_hermes_workspace_root "${NODE}")"

REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_DS="${REMOTE_HERMES_WS%/}/yuanrong-datasystem"

log_info "Hermes sync: ${DS_ROOT}/ -> ${REMOTE}:${REMOTE_DS}/"
log_info "Node: ${NODE} (${REMOTE})"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[dry-run] Would rsync:"
  echo "  rsync -az --delete \\"
  echo "    --exclude '.git/' --exclude 'build/' --exclude 'bazel-*' --exclude '.cache/' \\"
  echo "    ${DS_ROOT}/"
  echo "    ${REMOTE}:${REMOTE_DS}/"
  exit 0
fi

# Ensure remote dir exists
ssh -o BatchMode=yes "${REMOTE}" "mkdir -p ${REMOTE_HERMES_WS}"

# Sync datasystem only
rsync -az --delete \
  --exclude '.git/' \
  --exclude 'build/' \
  --exclude 'bazel-*' \
  --exclude '.cache/' \
  "${DS_ROOT}/" "${REMOTE}:${REMOTE_DS}/"

log_info "Hermes sync complete"
