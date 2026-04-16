#!/usr/bin/env bash
# =============================================================================
# verify_zmq_fault_injection_logs.sh
#
# After ZmqMetricsFaultTest.* (ds_st) completes, validates that **key log lines**
# required for fault localization appear in the captured output.
#
# Usage:
#   ./verify_zmq_fault_injection_logs.sh /path/to/ds_st_zmq_fault.log
#   ./verify_zmq_fault_injection_logs.sh --remote
#       (runs ssh + ds_st --gtest_filter=ZmqMetricsFaultTest.* and checks inline)
#
# Environment (with --remote):
#   REMOTE_HOST  default root@38.76.164.55
#   REMOTE_DS    default /root/workspace/git-repos/yuanrong-datasystem
#   REMOTE_BUILD default ${REMOTE_DS}/build
#
# Exit: 0 all mandatory patterns found; 1 missing mandatory pattern
# =============================================================================
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-root@38.76.164.55}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
REMOTE_BUILD="${REMOTE_BUILD:-${REMOTE_DS}/build}"
LOG_FILE=""

if [[ "${1:-}" == "--remote" ]]; then
  LOG_FILE="$(mktemp /tmp/zmq_fault_log.XXXXXX)"
  trap 'rm -f "$LOG_FILE"' EXIT
  ssh -o BatchMode=yes -o ConnectTimeout=20 "$REMOTE_HOST" bash -s <<EOF | tee "$LOG_FILE"
set -euo pipefail
cd "${REMOTE_BUILD}"
./tests/st/ds_st --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr 2>&1
EOF
elif [[ -n "${1:-}" && -f "$1" ]]; then
  LOG_FILE="$1"
else
  echo "Usage: $0 <logfile> | $0 --remote"
  exit 2
fi

echo "═══════════════════════════════════════════════════════════════════"
echo " ZMQ fault-injection log verification"
echo " Log: $LOG_FILE"
echo "═══════════════════════════════════════════════════════════════════"

PASS=0
FAIL=0

need() {
  local name="$1"
  local pattern="$2"
  if grep -qE "$pattern" "$LOG_FILE"; then
    echo "  ✓  $name"
    ((++PASS)) || true
  else
    echo "  ✗  MISSING: $name  (pattern: $pattern)"
    ((++FAIL)) || true
  fi
}

echo ""
echo "── Mandatory: gtest ──"
if grep -qE '\[  FAILED  \]' "$LOG_FILE"; then
  echo "  ✗  gtest reported FAILED"
  ((++FAIL)) || true
else
  ((++PASS)) || true
  echo "  ✓  No [ FAILED ] line in summary"
fi
need "gtest PASSED line present" '\[  PASSED  \]'
need "Four fault-injection cases" '\[----------\] 4 tests from ZmqMetricsFaultTest'

echo ""
echo "── Scenario: Normal RPCs + metrics dump ──"
need "METRICS DUMP tag (normal)" '\[METRICS DUMP - Normal RPCs\]'
need "Histogram lines (zmq.io)" 'zmq\.io\.(send|recv)_us,count='
need "Self-proof ratio line" '\[SELF-PROOF\] framework_ratio='

echo ""
echo "── Scenario: Server killed (peer crash) ──"
need "Fault inject: shutdown" '\[FAULT INJECT\] Shutting down server'
need "METRICS DUMP (server killed)" '\[METRICS DUMP - Server Killed\]'
need "Isolation gw_recreate line" '\[ISOLATION\] gw_recreate total='

echo ""
echo "── Scenario: Slow server (RPC timeout, ZMQ counters clean) ──"
need "Fault inject: World / slow" '\[FAULT INJECT\] Sending .World.'
need "METRICS DUMP (slow server)" '\[METRICS DUMP - Slow Server\]'
need "Isolation ZMQ layer clean" 'ZMQ layer clean|recv\.fail=0.*recv\.eagain=0'

echo ""
echo "── Scenario: High load self-proof ──"
need "METRICS DUMP (high load)" '\[METRICS DUMP - High Load\]'
need "SELF-PROOF REPORT block" '\[SELF-PROOF REPORT\]'
need "CONCLUSION line" 'CONCLUSION:'

echo ""
echo "── Optional: ZMQ socket hard-fail tags (only if errno path hit) ──"
if grep -qE '\[ZMQ_RECV_FAIL\]|\[ZMQ_SEND_FAIL\]' "$LOG_FILE"; then
  echo "  ℹ  Found [ZMQ_RECV_FAIL] or [ZMQ_SEND_FAIL] (hard ZMQ errno path exercised)"
  ((++PASS)) || true
else
  echo "  ○  No [ZMQ_RECV_FAIL]/[ZMQ_SEND_FAIL] in this run (expected for stub poll + clean TCP)"
fi

echo ""
echo "── Optional: blocking recv timeout tag (ZMQ_RCVTIMEO path) ──"
if grep -q '\[ZMQ_RECV_TIMEOUT\]' "$LOG_FILE"; then
  echo "  ℹ  Found [ZMQ_RECV_TIMEOUT]"
  ((++PASS)) || true
else
  echo "  ○  No [ZMQ_RECV_TIMEOUT] (fault tests use RpcOptions timeout + DONTWAIT stub path)"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo " Mandatory RESULT: $PASS matched | $FAIL missing"
echo "═══════════════════════════════════════════════════════════════════"

[[ "$FAIL" -eq 0 ]]
