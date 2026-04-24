#!/usr/bin/env bash
# Integration test (ST) on remote node via SSH (< 60 minutes).
#
# Usage:
#   bash scripts/testing/verify/st/run_st_remote.sh [--node <name>] [--skip-build]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../../../lib/load_nodes.sh"
. "${SCRIPT_DIR}/../../../../lib/remote_defaults.sh"
. "${SCRIPT_DIR}/../../../../lib/common.sh"

SKIP_BUILD=0
NODE="${NODE_NAME:-$(node_default)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    --node) NODE="$2"; shift 2 ;;
    *) shift ;;
  esac
done

init_remote "${NODE}"
BUILD_BACKEND="${BUILD_BACKEND:-cmake}"

banner "ST on ${REMOTE}"

ssh_remote "${REMOTE}" bash -c "
  set -euo pipefail
  cd ~/workspace/git-repos/yuanrong-datasystem

  if [[ '${SKIP_BUILD}' -eq 0 ]]; then
    echo 'Building...'
    bash build.sh -t build -B build -b ${BUILD_BACKEND} -j \$(nproc) 2>&1 | tail -5
  fi

  echo 'Running ST tests...'
  ctest --test-dir build --output-on-failure -R 'st|ST|integration' -j \$(nproc) 2>&1 | tail -30
"
