#!/usr/bin/env bash
# =============================================================================
# Phase 1 — ZMQ metrics UT regression（ZmqMetricsTest + MetricsTest）on remote.
#
# What it does:
#   1) rsync local yuanrong-datasystem → remote
#   2) Build: BUILD_BACKEND=bazel（默认）: bazel build + bazel run 两个 UT 目标
#            BUILD_BACKEND=cmake: cmake --build ds_ut
#   3) Run:
#      - bazel: zmq_metrics_test --gtest_filter=ZmqMetricsTest.*
#               metrics_test --gtest_filter=MetricsTest.*
#      - cmake: ds_ut --gtest_filter='ZmqMetricsTest.*:MetricsTest.*'（与 PR 文档一致）
#
# Environment:
#   BUILD_BACKEND   bazel | cmake（默认 bazel）
#   REMOTE_HOST     default: xqyun-32c32g
#   REMOTE_DS       default: /root/workspace/git-repos/yuanrong-datasystem
#   REMOTE_BUILD    default: ${REMOTE_DS}/build
#   LOCAL_DS        default: sibling repo from this script
#   BUILD_JOBS      default: 8
#   BAZEL_UT_ZMQ    default //tests/ut/common/rpc:zmq_metrics_test
#   BAZEL_UT_METRICS default //tests/ut/common/metrics:metrics_test
#
# Evidence: EVIDENCE_LOG (default: /tmp/zmq_metrics_ut_regression.log)
# =============================================================================
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-xqyun-32c32g}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
REMOTE_BUILD="${REMOTE_BUILD:-${REMOTE_DS}/build}"
BUILD_JOBS="${BUILD_JOBS:-8}"
BUILD_BACKEND="${BUILD_BACKEND:-bazel}"
EVIDENCE_LOG="${EVIDENCE_LOG:-/tmp/zmq_metrics_ut_regression.log}"

BAZEL_UT_ZMQ="${BAZEL_UT_ZMQ:-//tests/ut/common/rpc:zmq_metrics_test}"
BAZEL_UT_METRICS="${BAZEL_UT_METRICS:-//tests/ut/common/metrics:metrics_test}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DS="${LOCAL_DS:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd || true)}"
if [[ ! -d "$LOCAL_DS" ]]; then
  echo "ERROR: LOCAL_DS not found. Set LOCAL_DS=/path/to/yuanrong-datasystem"
  exit 2
fi

echo "═══════════════════════════════════════════════════════════════════"
echo " Phase 1: ZMQ metrics UT regression (remote)  BUILD_BACKEND=$BUILD_BACKEND"
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
    --exclude 'bazel-*' \
    "${LOCAL_DS}/" "${REMOTE_HOST}:${REMOTE_DS}/"

  ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE_HOST" \
    env \
      REMOTE_DS="$REMOTE_DS" \
      REMOTE_BUILD="$REMOTE_BUILD" \
      BUILD_JOBS="$BUILD_JOBS" \
      BUILD_BACKEND="$BUILD_BACKEND" \
      BAZEL_UT_ZMQ="$BAZEL_UT_ZMQ" \
      BAZEL_UT_METRICS="$BAZEL_UT_METRICS" \
    bash -s <<'REMOTE_EOF'
set -euo pipefail
if [[ "${BUILD_BACKEND}" == "cmake" ]]; then
  cd "${REMOTE_BUILD}"
  echo "=== cmake build ds_ut (jobs=${BUILD_JOBS}) ==="
  cmake --build . --target ds_ut -j"${BUILD_JOBS}"
  echo "=== ds_ut ZmqMetricsTest.* + MetricsTest.* ==="
  ./tests/ut/ds_ut --gtest_filter='ZmqMetricsTest.*:MetricsTest.*' --alsologtostderr
else
  cd "${REMOTE_DS}"
  echo "=== bazel build UT targets (jobs=${BUILD_JOBS}) ==="
  bazel build "${BAZEL_UT_ZMQ}" "${BAZEL_UT_METRICS}" --jobs="${BUILD_JOBS}"
  echo "=== ZmqMetricsTest.* ==="
  bazel run "${BAZEL_UT_ZMQ}" -- --gtest_filter='ZmqMetricsTest.*' --alsologtostderr
  echo "=== MetricsTest.* ==="
  bazel run "${BAZEL_UT_METRICS}" -- --gtest_filter='MetricsTest.*' --alsologtostderr
fi
REMOTE_EOF

  echo "=== $(date -Is) end (exit 0) ==="
} 2>&1 | tee "$EVIDENCE_LOG"

echo ""
echo "Done. Evidence saved to: $EVIDENCE_LOG"
