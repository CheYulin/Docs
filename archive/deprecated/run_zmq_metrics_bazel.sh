#!/usr/bin/env bash
# =============================================================================
# run_zmq_metrics_bazel.sh
#
# Build and run ZMQ metrics–related tests with Bazel (UT + ST).
#
# Usage (from anywhere):
#   ./run_zmq_metrics_bazel.sh
#   LOCAL_DS=/path/to/yuanrong-datasystem ./run_zmq_metrics_bazel.sh
#   BAZEL_CMD=bazelisk ./run_zmq_metrics_bazel.sh
#
#   --remote   ssh to REMOTE_HOST and run the same bazel commands in REMOTE_DS
#
# Targets (override via env if needed):
#   BAZEL_UT_ZMQ   default //tests/ut/common/rpc:zmq_metrics_test
#   BAZEL_ST_FAULT default //tests/st/common/rpc/zmq:zmq_metrics_fault_test
#
# Filters:
#   UT:  ZmqMetricsTest.*
#   ST:  ZmqMetricsFaultTest.*
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DS="${LOCAL_DS:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd || true)}"
BAZEL_CMD="${BAZEL_CMD:-bazel}"
REMOTE_HOST="${REMOTE_HOST:-xqyun-32c32g}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
BAZEL_UT_ZMQ="${BAZEL_UT_ZMQ:-//tests/ut/common/rpc:zmq_metrics_test}"
BAZEL_ST_FAULT="${BAZEL_ST_FAULT:-//tests/st/common/rpc/zmq:zmq_metrics_fault_test}"
REMOTE_MODE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote) REMOTE_MODE=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--remote]  (set LOCAL_DS or run from repo; BAZEL_CMD=bazelisk optional)"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 2 ;;
  esac
done

run_local() {
  [[ -d "$LOCAL_DS" ]] || { echo "ERROR: LOCAL_DS not found: $LOCAL_DS"; exit 2; }
  cd "$LOCAL_DS"
  echo "═══ $BAZEL_CMD build $BAZEL_UT_ZMQ $BAZEL_ST_FAULT ═══"
  "$BAZEL_CMD" build "$BAZEL_UT_ZMQ" "$BAZEL_ST_FAULT"

  echo "═══ UT: $BAZEL_UT_ZMQ  (ZmqMetricsTest.*) ═══"
  "$BAZEL_CMD" run "$BAZEL_UT_ZMQ" -- --gtest_filter='ZmqMetricsTest.*' --alsologtostderr

  echo "═══ ST: $BAZEL_ST_FAULT  (ZmqMetricsFaultTest.*) ═══"
  "$BAZEL_CMD" run "$BAZEL_ST_FAULT" -- --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr
}

if [[ "$REMOTE_MODE" == true ]]; then
  echo "═══ Remote: $REMOTE_HOST:$REMOTE_DS ═══"
  ssh -o BatchMode=yes -o ConnectTimeout=20 "$REMOTE_HOST" \
    env \
      REMOTE_DS="$REMOTE_DS" \
      BAZEL_CMD="$BAZEL_CMD" \
      BAZEL_UT_ZMQ="$BAZEL_UT_ZMQ" \
      BAZEL_ST_FAULT="$BAZEL_ST_FAULT" \
    bash -s <<'REMOTE_EOF'
set -euo pipefail
cd "$REMOTE_DS"
echo "=== $BAZEL_CMD build ==="
"$BAZEL_CMD" build "$BAZEL_UT_ZMQ" "$BAZEL_ST_FAULT"
echo "=== UT ==="
"$BAZEL_CMD" run "$BAZEL_UT_ZMQ" -- --gtest_filter='ZmqMetricsTest.*' --alsologtostderr
echo "=== ST ==="
"$BAZEL_CMD" run "$BAZEL_ST_FAULT" -- --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr
REMOTE_EOF
else
  run_local
fi
