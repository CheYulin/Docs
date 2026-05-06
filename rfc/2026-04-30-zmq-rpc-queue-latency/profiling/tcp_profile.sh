#!/usr/bin/env bash
# TCP profiling: capture TCP stack metrics during REPL test run.
#
# Samples /proc/net/snmp, /proc/net/netstat, and ss -ti every 2 seconds
# during the test to detect retransmits, connection state, and socket buffer usage.
#
# Usage (from scripts/):
#   ./tcp_profile.sh            # 10s run (default)
#   ./tcp_profile.sh 15        # custom duration
#
# Output (scp'd back to LOCAL_RESULTS_DIR/):
#   tcp_profile_report.txt     - all captured TCP metrics with timestamps

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=repl_remote_common.inc.sh
source "${SCRIPT_DIR}/repl_remote_common.inc.sh"

TCP_REPORT_REMOTE="/tmp/tcp_profile_report.txt"
DURATION="${1:-${DURATION:-10}}"

echo "=== tcp_profile: REMOTE=${REMOTE} DURATION=${DURATION}s ==="
echo

mkdir -p "${LOCAL_RESULTS_DIR}"

echo "=== Starting REPL test with TCP monitoring (${DURATION}s) ==="

ssh "${REMOTE}" bash -s "${REMOTE_DS}" "${DS_OPENSOURCE_DIR_REMOTE}" "${BAZEL_JOBS}" \
  "${REPL_BAZEL_TARGET}" "${DURATION}" "${TCP_REPORT_REMOTE}" <<'REMOTESCRIPT'
set -euo pipefail
REMOTE_DS="$1"
DS_OP="$2"
JOBS="$3"
TARGET="$4"
DUR="$5"
REPORT_OUT="$6"

export DS_OPENSOURCE_DIR="${DS_OP}"
mkdir -p "${DS_OPENSOURCE_DIR}"
cd "${REMOTE_DS}"

rm -f "${REPORT_OUT}"

REPL_LOG_REMOTE="/tmp/zmq_repl_tcp.log"

exec 3>&1

tee_and_log() {
  echo "$1" | tee /dev/fd/3
}

# Header (to TCP report)
{
  echo "========================================"
  echo "TCP Profiling Report — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "Duration: ${DUR}s, Target: ${TARGET}"
  echo "========================================"
  echo ""
} > "${REPORT_OUT}"

# Snapshot BEFORE
{
  echo "--- TCP SNAPSHOT BEFORE (t=0) ---"
  date '+%H:%M:%S'
  cat /proc/net/snmp
  echo "--- netstat extended ---"
  cat /proc/net/netstat
  echo "--- ss -ti established (sample) ---"
  ss -ti state established 2>/dev/null | head -20 || echo "ss failed"
  echo ""
} >> "${REPORT_OUT}"

# Start REPL in background
echo "--- Starting REPL binary ---"
DS_OPENSOURCE_DIR="${DS_OP}" bazel run "${TARGET}" \
  --test_env=ZMQ_RPC_QUEUE_LATENCY_SEC="${DUR}" \
  --test_arg=--logtostderr=1 --test_arg=--v=0 \
  -- --logtostderr=1 --v=0 \
  > "${REPL_LOG_REMOTE}" 2>&1 &
REPL_PID=$!
sleep 2

INTERVAL=2
SAMPLES=$(( DUR / INTERVAL ))
for i in $(seq 1 "${SAMPLES}"); do
  ELAPSED=$(( i * INTERVAL ))
  {
    echo "--- TCP SNAPSHOT t=${ELAPSED}s (sample ${i}/${SAMPLES}) ---"
    date '+%H:%M:%S'
    echo "--- /proc/net/snmp (RetransSegs key line) ---"
    grep -E "RetransSegs|OutSegs|InSegs|Tcp.*:" /proc/net/snmp
    echo "--- /proc/net/netstat RetransSegs ---"
    grep -iE "RetransSegs|TcpExt.*Reorder" /proc/net/netstat
    echo "--- ss -ti (top 10) ---"
    ss -ti state established 2>/dev/null | head -10 || echo "ss failed"
    echo ""
  } >> "${REPORT_OUT}"
  if [ $i -lt "${SAMPLES}" ]; then
    sleep "${INTERVAL}"
  fi
done

wait ${REPL_PID} 2>/dev/null || true

# Snapshot AFTER
{
  echo "--- TCP SNAPSHOT AFTER (t=end) ---"
  date '+%H:%M:%S'
  grep -E "RetransSegs|OutSegs|InSegs|Tcp.*:" /proc/net/snmp
  grep -iE "RetransSegs|TcpExt.*Reorder" /proc/net/netstat
  ss -ti state established 2>/dev/null | head -20 || echo "ss failed"
  echo ""
  echo "=== REPL stderr/stdout tail ==="
  tail -20 "${REPL_LOG_REMOTE}"
} >> "${REPORT_OUT}"

echo "TCP profiling complete. Report at ${REPORT_OUT}"
REMOTESCRIPT

REMOTE_RC=$?

echo
echo "=== SCP tcp report back to ${LOCAL_RESULTS_DIR}/ ==="
scp "${REMOTE}:${TCP_REPORT_REMOTE}" "${LOCAL_RESULTS_DIR}/tcp_profile_report.txt" 2>/dev/null && \
  echo "tcp_profile done, $(wc -l < "${LOCAL_RESULTS_DIR}/tcp_profile_report.txt") lines." || \
  echo "scp tcp report failed (exit ${?})"

exit ${REMOTE_RC}
