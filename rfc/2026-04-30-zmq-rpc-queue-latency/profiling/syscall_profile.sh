#!/usr/bin/env bash
# Syscall profiling: strace -c to capture per-syscall time + call counts during REPL test.
#
# strace -c aggregates time spent in each syscall category (calls, errors, syscall name).
# This tells us whether the process is CPU-bound (instructions), blocked on I/O (read/write/send/recv),
# waiting on epoll/ppoll (network I/O multiplexing), or hitting futex/condvar contention.
#
# Usage (from scripts/):
#   ./syscall_profile.sh            # 10s run (default)
#   ./syscall_profile.sh 15         # custom duration
#
# Output (scp'd back to LOCAL_RESULTS_DIR/):
#   syscall_profile_report.txt       - strace -c output (calls, errors, time per syscall)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=repl_remote_common.inc.sh
source "${SCRIPT_DIR}/repl_remote_common.inc.sh"

STRACE_REPORT_REMOTE="/tmp/strace_c_report.txt"
DURATION="${1:-${DURATION:-10}}"

echo "=== syscall_profile: REMOTE=${REMOTE} DURATION=${DURATION}s ==="
echo

mkdir -p "${LOCAL_RESULTS_DIR}"

echo "=== Check strace availability on remote ==="
ssh "${REMOTE}" 'command -v strace && strace -V 2>&1 | head -1 || { echo "strace not found on remote"; exit 1; }'

echo
echo "=== Starting REPL test under strace -c (${DURATION}s) ==="

ssh "${REMOTE}" bash -s "${REMOTE_DS}" "${DS_OPENSOURCE_DIR_REMOTE}" "${BAZEL_JOBS}" \
  "${REPL_BAZEL_TARGET}" "${DURATION}" "${STRACE_REPORT_REMOTE}" <<'REMOTESCRIPT'
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

echo "========================================"
echo "Syscall Profile — $(date '+%Y-%m-%d %H:%M:%S')"
echo "Duration: ${DUR}s, Target: ${TARGET}"
echo "========================================"
echo ""

# Check if strace works
if ! command -v strace > /dev/null 2>&1; then
  echo "ERROR: strace not installed on remote" | tee "${REPORT_OUT}"
  exit 1
fi

# Start REPL with strace -c -f (follow forks/vthreads)
# -c: summary table  -f: follow children  -tt: timestamp with us
echo "=== Starting: strace -c -f -tt -T (${DUR}s) ==="
DS_OPENSOURCE_DIR="${DS_OP}" timeout "$((DUR + 5))" \
  strace -c -f -tt -T \
  bazel run "${TARGET}" \
    --test_env=ZMQ_RPC_QUEUE_LATENCY_SEC="${DUR}" \
    --test_arg=--logtostderr=1 --test_arg=--v=0 \
    -- --logtostderr=1 --v=0 \
  > /tmp/strace_output.txt 2>&1 &
STRACE_PID=$!

wait ${STRACE_PID} 2>/dev/null || true

echo ""
echo "=== strace output ==="
cat /tmp/strace_output.txt

# Extract the summary table (after the syscall traces)
# The summary appears after a line like "% time     seconds  usecs/call     calls    errors syscall"
{
  echo ""
  echo "========================================"
  echo "Syscall Summary Table"
  echo "========================================"
  # Find the table header and everything after it
  awk '/^% time/ {found=1} found' /tmp/strace_output.txt
} > "${REPORT_OUT}"

echo ""
echo "=== Report saved to ${REPORT_OUT} ==="
echo "Lines: $(wc -l < "${REPORT_OUT}")"
REMOTESCRIPT

REMOTE_RC=$?

echo
echo "=== SCP syscall report back to ${LOCAL_RESULTS_DIR}/ ==="
scp "${REMOTE}:${STRACE_REPORT_REMOTE}" "${LOCAL_RESULTS_DIR}/syscall_profile_report.txt" 2>/dev/null && \
  echo "syscall_profile done, $(wc -l < "${LOCAL_RESULTS_DIR}/syscall_profile_report.txt") lines." || \
  echo "scp syscall report failed (exit ${?})"

exit ${REMOTE_RC}
