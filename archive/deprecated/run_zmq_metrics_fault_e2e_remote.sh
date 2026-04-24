#!/usr/bin/env bash
# =============================================================================
# Phase 2 — ZMQ metrics fault-injection E2E (ZmqMetricsFaultTest) + verify_zmq_metrics_fault.sh
#
# Runs on remote after syncing datasystem, then invokes verify_zmq_metrics_fault.sh --remote.
#
# Environment:
#   BUILD_BACKEND   bazel | cmake（默认 bazel）
#   REMOTE_HOST, REMOTE_DS, LOCAL_DS, BUILD_JOBS — same as run_zmq_metrics_ut_regression_remote.sh
#   BAZEL_TARGET  — default //tests/st/common/rpc/zmq:zmq_metrics_fault_test
#   SKIP_RSYNC=1  — only run remote build+test+verify (tree must already be synced)
#   EVIDENCE_LOG  — default /tmp/zmq_metrics_fault_e2e.log
# =============================================================================
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-xqyun-32c32g}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
REMOTE_BUILD="${REMOTE_BUILD:-${REMOTE_DS}/build}"
BUILD_JOBS="${BUILD_JOBS:-8}"
BUILD_BACKEND="${BUILD_BACKEND:-bazel}"
BAZEL_TARGET="${BAZEL_TARGET:-//tests/st/common/rpc/zmq:zmq_metrics_fault_test}"
SKIP_RSYNC="${SKIP_RSYNC:-0}"
EVIDENCE_LOG="${EVIDENCE_LOG:-/tmp/zmq_metrics_fault_e2e.log}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DS="${LOCAL_DS:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd || true)}"
VERIFY_SH="${SCRIPT_DIR}/verify_zmq_metrics_fault.sh"

if [[ ! -x "$VERIFY_SH" && -f "$VERIFY_SH" ]]; then
  chmod +x "$VERIFY_SH" || true
fi

echo "═══════════════════════════════════════════════════════════════════"
echo " Phase 2: ZMQ fault-injection E2E + verify_zmq_metrics_fault.sh"
echo " BUILD_BACKEND=$BUILD_BACKEND"
echo " LOCAL_DS=$LOCAL_DS"
echo " REMOTE=$REMOTE_HOST:$REMOTE_DS"
echo " Evidence: $EVIDENCE_LOG"
echo "═══════════════════════════════════════════════════════════════════"

{
  echo "=== $(date -Is) start ==="
  if [[ "$SKIP_RSYNC" != "1" ]]; then
    [[ ! -d "$LOCAL_DS" ]] && { echo "ERROR: LOCAL_DS=$LOCAL_DS"; exit 2; }
    rsync -az --delete \
      --exclude '.git/' \
      --exclude 'build/' \
      --exclude '.cache/' \
      "${LOCAL_DS}/" "${REMOTE_HOST}:${REMOTE_DS}/"
  else
    echo "SKIP_RSYNC=1 — using existing remote tree"
  fi

  ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE_HOST" \
    env \
      REMOTE_DS="$REMOTE_DS" \
      REMOTE_BUILD="$REMOTE_BUILD" \
      BUILD_JOBS="$BUILD_JOBS" \
      BUILD_BACKEND="$BUILD_BACKEND" \
      BAZEL_TARGET="$BAZEL_TARGET" \
    bash -s <<'REMOTE_EOF'
set -euo pipefail
if [[ "${BUILD_BACKEND}" == "cmake" ]]; then
  cd "${REMOTE_BUILD}"
  echo "=== cmake build ds_st (jobs=${BUILD_JOBS}) ==="
  cmake --build . --target ds_st -j"${BUILD_JOBS}"
else
  cd "${REMOTE_DS}"
  echo "=== bazel build ${BAZEL_TARGET} (jobs=${BUILD_JOBS}) ==="
  bazel build "${BAZEL_TARGET}" --jobs="${BUILD_JOBS}"
fi
REMOTE_EOF

  echo "=== verify_zmq_metrics_fault.sh --remote ==="
  export BAZEL_TARGET REMOTE_DS REMOTE_HOST REMOTE_BUILD BUILD_BACKEND
  if [[ "${BUILD_BACKEND}" == "cmake" ]]; then
    bash "$VERIFY_SH" --remote --backend cmake
  else
    bash "$VERIFY_SH" --remote --backend bazel
  fi

  echo "=== $(date -Is) end (exit 0) ==="
} 2>&1 | tee "$EVIDENCE_LOG"

echo ""
echo "Done. Evidence saved to: $EVIDENCE_LOG"
