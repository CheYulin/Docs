#!/usr/bin/env bash
# =============================================================================
# ZMQ RPC metrics 定界 — 远端全链路（对齐 plan 文档：UT + ST + 两套 verify）
#
# 1) rsync local yuanrong-datasystem → remote
# 2) 构建：BUILD_BACKEND=bazel（默认）或 cmake
# 3) UT：ZmqMetricsTest.* + MetricsTest.*（与 ds_ut 单测过滤等价）
# 4) ST：ZmqMetricsFaultTest.*，日志落盘并 scp 回本机
# 5) verify_zmq_metrics_fault.sh --input-log（不重复跑 ST）
# 6) verify_zmq_fault_injection_logs.sh <log>
#
# 环境变量（均可覆盖）：
#   BUILD_BACKEND   bazel | cmake   （默认 bazel）
#   REMOTE_HOST     默认 xqyun-32c32g
#   REMOTE_DS       默认 /root/workspace/git-repos/yuanrong-datasystem
#   LOCAL_DS        默认脚本旁 yuanrong-datasystem
#   BUILD_JOBS      默认 8
#   SKIP_RSYNC=1    不同步，仅远端执行
#   EVIDENCE_LOG    默认 /tmp/zmq_rpc_metrics_full.log
#   BAZEL_CMD       默认 bazel（远端 BUILD_BACKEND=bazel 时使用；可设为 bazelisk）
#
# Bazel 目标（可通过环境覆盖）：
#   BAZEL_UT_ZMQ=//tests/ut/common/rpc:zmq_metrics_test
#   BAZEL_UT_METRICS=//tests/ut/common/metrics:metrics_test
#   BAZEL_ST_FAULT=//tests/st/common/rpc/zmq:zmq_metrics_fault_test
# =============================================================================
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-xqyun-32c32g}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
REMOTE_BUILD="${REMOTE_BUILD:-${REMOTE_DS}/build}"
BUILD_JOBS="${BUILD_JOBS:-8}"
BUILD_BACKEND="${BUILD_BACKEND:-bazel}"
SKIP_RSYNC="${SKIP_RSYNC:-0}"
EVIDENCE_LOG="${EVIDENCE_LOG:-/tmp/zmq_rpc_metrics_full.log}"

BAZEL_UT_ZMQ="${BAZEL_UT_ZMQ:-//tests/ut/common/rpc:zmq_metrics_test}"
BAZEL_UT_METRICS="${BAZEL_UT_METRICS:-//tests/ut/common/metrics:metrics_test}"
BAZEL_ST_FAULT="${BAZEL_ST_FAULT:-//tests/st/common/rpc/zmq:zmq_metrics_fault_test}"
BAZEL_CMD="${BAZEL_CMD:-bazel}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DS="${LOCAL_DS:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd || true)}"
VERIFY_METRICS="${SCRIPT_DIR}/verify_zmq_metrics_fault.sh"
VERIFY_LOGS="${SCRIPT_DIR}/verify_zmq_fault_injection_logs.sh"

for f in "$VERIFY_METRICS" "$VERIFY_LOGS"; do
  [[ -f "$f" ]] || { echo "ERROR: missing $f"; exit 2; }
  [[ -x "$f" ]] || chmod +x "$f" || true
done

if [[ ! -d "$LOCAL_DS" && "$SKIP_RSYNC" != "1" ]]; then
  echo "ERROR: LOCAL_DS not found: $LOCAL_DS"
  exit 2
fi

# Use /tmp on remote so rsync --delete does not remove the log under the repo tree.
ST_LOG_REMOTE="${ST_LOG_REMOTE:-/tmp/zmq_metrics_fault_st_last.log}"
ST_LOG_LOCAL="${ST_LOG_LOCAL:-/tmp/zmq_metrics_fault_st_last.log}"

echo "═══════════════════════════════════════════════════════════════════"
echo " ZMQ RPC metrics — full remote run"
echo " BUILD_BACKEND=$BUILD_BACKEND  BAZEL_CMD=$BAZEL_CMD"
echo " LOCAL_DS=$LOCAL_DS"
echo " REMOTE=$REMOTE_HOST:$REMOTE_DS"
echo " Evidence: $EVIDENCE_LOG"
echo "═══════════════════════════════════════════════════════════════════"

{
  echo "=== $(date -Is) start ==="
  if [[ "$SKIP_RSYNC" != "1" ]]; then
    rsync -az --delete \
      --exclude '.git/' \
      --exclude 'build/' \
      --exclude '.cache/' \
      --exclude 'bazel-*' \
      --exclude 'MODULE.bazel.lock' \
      "${LOCAL_DS}/" "${REMOTE_HOST}:${REMOTE_DS}/"
  else
    echo "SKIP_RSYNC=1 — using existing remote tree"
  fi

  ssh -o BatchMode=yes -o ConnectTimeout=20 "$REMOTE_HOST" \
    env \
      REMOTE_DS="$REMOTE_DS" \
      REMOTE_BUILD="$REMOTE_BUILD" \
      BUILD_JOBS="$BUILD_JOBS" \
      BUILD_BACKEND="$BUILD_BACKEND" \
      BAZEL_UT_ZMQ="$BAZEL_UT_ZMQ" \
      BAZEL_UT_METRICS="$BAZEL_UT_METRICS" \
      BAZEL_ST_FAULT="$BAZEL_ST_FAULT" \
      BAZEL_CMD="$BAZEL_CMD" \
      ST_LOG_REMOTE="$ST_LOG_REMOTE" \
    bash -s <<'REMOTE_EOF'
set -euo pipefail
if [[ "${BUILD_BACKEND}" == "cmake" ]]; then
  cd "${REMOTE_BUILD}"
  echo "=== cmake: ds_ut + ds_st (jobs=${BUILD_JOBS}) ==="
  cmake --build . --target ds_ut ds_st -j"${BUILD_JOBS}"

  echo "=== UT: ZmqMetricsTest.* + MetricsTest.* (ds_ut) ==="
  ./tests/ut/ds_ut --gtest_filter='ZmqMetricsTest.*:MetricsTest.*' --alsologtostderr

  echo "=== ST: ZmqMetricsFaultTest.* → ${ST_LOG_REMOTE} ==="
  ./tests/st/ds_st --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr 2>&1 | tee "${ST_LOG_REMOTE}"
else
  cd "${REMOTE_DS}"
  echo "=== ${BAZEL_CMD} build UT+ST targets (jobs=${BUILD_JOBS}) ==="
  "${BAZEL_CMD}" build "${BAZEL_UT_ZMQ}" "${BAZEL_UT_METRICS}" "${BAZEL_ST_FAULT}" --jobs="${BUILD_JOBS}"

  echo "=== UT: ZmqMetricsTest.* ==="
  "${BAZEL_CMD}" run "${BAZEL_UT_ZMQ}" -- --gtest_filter='ZmqMetricsTest.*' --alsologtostderr

  echo "=== UT: MetricsTest.* ==="
  "${BAZEL_CMD}" run "${BAZEL_UT_METRICS}" -- --gtest_filter='MetricsTest.*' --alsologtostderr

  echo "=== ST: ZmqMetricsFaultTest.* → ${ST_LOG_REMOTE} ==="
  "${BAZEL_CMD}" run "${BAZEL_ST_FAULT}" -- --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr 2>&1 | tee "${ST_LOG_REMOTE}"
fi
REMOTE_EOF

  echo "=== scp ST log → $ST_LOG_LOCAL ==="
  scp -o BatchMode=yes -o ConnectTimeout=20 "${REMOTE_HOST}:${ST_LOG_REMOTE}" "$ST_LOG_LOCAL"

  echo "=== verify_zmq_metrics_fault.sh --input-log ==="
  bash "$VERIFY_METRICS" --input-log "$ST_LOG_LOCAL"

  echo "=== verify_zmq_fault_injection_logs.sh ==="
  bash "$VERIFY_LOGS" "$ST_LOG_LOCAL"

  echo "=== $(date -Is) end (exit 0) ==="
} 2>&1 | tee "$EVIDENCE_LOG"

echo ""
echo "Done. Full transcript: $EVIDENCE_LOG"
echo "ST log copy: $ST_LOG_LOCAL"
