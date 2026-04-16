#!/usr/bin/env bash
# =============================================================================
# Phase 1 — ZMQ metrics UT regression on a remote build tree (datasystem).
#
# What it does:
#   1) rsync local yuanrong-datasystem → remote (same layout as dev machines)
#   2) cmake --build … --target ds_ut
#   3) ./tests/ut/ds_ut --gtest_filter=ZmqMetricsTest.*
#
# Environment (override as needed):
#   REMOTE_HOST     default: root@38.76.164.55
#   REMOTE_DS       default: /root/workspace/git-repos/yuanrong-datasystem
#   LOCAL_DS        default: sibling repo resolved from this script
#   BUILD_JOBS      default: 8
#
# Evidence: full log is written to EVIDENCE_LOG (default: /tmp/zmq_metrics_ut_regression.log)
# =============================================================================
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@38.76.164.55}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
BUILD_JOBS="${BUILD_JOBS:-8}"
EVIDENCE_LOG="${EVIDENCE_LOG:-/tmp/zmq_metrics_ut_regression.log}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Default: vibe-coding-files/scripts/testing/verify → ../../../../yuanrong-datasystem (sibling under git-repos)
LOCAL_DS="${LOCAL_DS:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd || true)}"
if [[ ! -d "$LOCAL_DS" ]]; then
  echo "ERROR: LOCAL_DS not found. Set LOCAL_DS=/path/to/yuanrong-datasystem"
  exit 2
fi

echo "═══════════════════════════════════════════════════════════════════"
echo " Phase 1: ZMQ metrics UT regression (remote)"
echo " LOCAL_DS=$LOCAL_DS"
echo " REMOTE=$REMOTE_HOST:$REMOTE_DS"
echo " Evidence log: $EVIDENCE_LOG"
echo "═══════════════════════════════════════════════════════════════════"

{
  echo "=== $(date -Is) start ==="
  echo "LOCAL_DS=$LOCAL_DS"
  echo "REMOTE_HOST=$REMOTE_HOST REMOTE_DS=$REMOTE_DS"
  rsync -az --delete \
    --exclude '.git/' \
    --exclude 'build/' \
    --exclude '.cache/' \
    "${LOCAL_DS}/" "${REMOTE_HOST}:${REMOTE_DS}/"

  ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE_HOST" bash -s <<REMOTE_EOF
set -euo pipefail
cd "${REMOTE_DS}/build"
echo "=== cmake build ds_ut (jobs=${BUILD_JOBS}) ==="
cmake --build . --target ds_ut -j"${BUILD_JOBS}"
echo "=== run ZmqMetricsTest.* ==="
./tests/ut/ds_ut --gtest_filter='ZmqMetricsTest.*' --alsologtostderr
REMOTE_EOF

  echo "=== $(date -Is) end (exit 0) ==="
} 2>&1 | tee "$EVIDENCE_LOG"

echo ""
echo "Done. Evidence saved to: $EVIDENCE_LOG"
