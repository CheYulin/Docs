#!/usr/bin/env bash
# Perf profiling: perf stat (hardware counters) + perf record (flamegraph) for zmq_rpc_queue_latency_repl
#
# Runs the REPL binary on remote for DURATION seconds, profiled by perf stat (1s intervals)
# and perf record (99Hz, 8s), then scp's back perf.data + all reports.
#
# Usage (from scripts/):
#   ./perf_profile.sh              # 10s run, default output dir
#   ./perf_profile.sh 15           # custom duration
#   DURATION=20 ./perf_profile.sh  # via env
#
# Dependencies on remote:
#   - perf(1) installed (package: perf or linux-tools)
#   - python3+graphviz (for flamegraph.pl if generating flame svg)
#
# Output (scp'd back to LOCAL_RESULTS_DIR/):
#   perf_stat_report.txt   - perf stat output (1s interval hardware counters)
#   perf_record_report.txt - perf report --stdio (top callers from flame data)
#   perf.data.gz           - compressed perf data (for local flamegraph.pl)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=repl_remote_common.inc.sh
source "${SCRIPT_DIR}/repl_remote_common.inc.sh"

PERF_STAT_REMOTE="/tmp/perf_stat_output.txt"
PERF_RECORD_REMOTE="/tmp/perf_record_output.txt"
PERF_DATA_REMOTE="/tmp/perf.data"
PERF_FLAME_REMOTE="/tmp/flamegraph.svg"

DURATION="${1:-${DURATION:-10}}"
PERF_EVENTS="cycles,instructions,cache-references,cache-misses,branches,branch-misses,context-switches,cpu-clock,task-clock,page-faults"

echo "=== perf_profile: REMOTE=${REMOTE} DURATION=${DURATION}s ==="
echo

mkdir -p "${LOCAL_RESULTS_DIR}"

echo "=== Step 1: Check remote perf availability ==="
ssh "${REMOTE}" 'command -v perf && perf --version || { echo "perf not found on remote"; exit 1; }'

echo
echo "=== Step 2: Start REPL test in background, then perf stat it ==="

# Strategy: run REPL in background, wait for process to appear, then perf stat it.
# This avoids bazel run hanging on tty.
ssh "${REMOTE}" bash -s "${REMOTE_DS}" "${DS_OPENSOURCE_DIR_REMOTE}" "${BAZEL_JOBS}" \
  "${REPL_BAZEL_TARGET}" "${DURATION}" "${PERF_EVENTS}" \
  "${PERF_STAT_REMOTE}" "${PERF_RECORD_REMOTE}" "${PERF_DATA_REMOTE}" "${PERF_FLAME_REMOTE}" <<'REMOTESCRIPT'
set -euo pipefail
REMOTE_DS="$1"
DS_OP="$2"
JOBS="$3"
TARGET="$4"
DUR="$5"
PERF_EVENTS="$6"
PERF_STAT_OUT="$7"
PERF_RECORD_OUT="$8"
PERF_DATA="$9"
PERF_FG="${10}"

export DS_OPENSOURCE_DIR="${DS_OP}"
mkdir -p "${DS_OPENSOURCE_DIR}"
cd "${REMOTE_DS}"

# Clean old outputs
rm -f "${PERF_STAT_OUT}" "${PERF_RECORD_OUT}" "${PERF_DATA}" "${PERF_FG}"

echo "=== Starting REPL test (${DUR}s) in background ==="
DS_OPENSOURCE_DIR="${DS_OP}" bazel run "${TARGET}" \
  --config=perf --config=release \
  --test_env=ZMQ_RPC_QUEUE_LATENCY_SEC="${DUR}" \
  --test_arg=--logtostderr=1 --test_arg=--v=0 \
  -- --logtostderr=1 --v=0 \
  > /tmp/zmq_repl_perf.log 2>&1 &
REPL_PID=$!
echo "REPL started with PID=${REPL_PID}"

# perf stat: system-wide (-a), no PID needed — works through Bazel sandbox
echo "=== perf stat -a (1s interval, ${DUR}s) ==="
perf stat -a \
  -e "${PERF_EVENTS}" \
  -I 1000 \
  > "${PERF_STAT_OUT}" 2>&1 &
PERF_STAT_PID=$!
echo "perf stat started with PID=${PERF_STAT_PID}"

# Let perf stat run for DUR seconds
wait ${REPL_PID} || true
echo "REPL finished"

# Stop perf stat
kill -INT ${PERF_STAT_PID} 2>/dev/null || true
wait ${PERF_STAT_PID} 2>/dev/null || true
echo "perf stat finished"

echo
echo "=== perf stat output ==="
cat "${PERF_STAT_OUT}"

# --- perf record (separate run, shorter) ---
echo
echo "=== Starting fresh REPL for perf record (8s, 99Hz) ==="
rm -f "${PERF_DATA}" "${PERF_FG}"
DS_OPENSOURCE_DIR="${DS_OP}" bazel run "${TARGET}" \
  --config=perf --config=release \
  --test_env=ZMQ_RPC_QUEUE_LATENCY_SEC=8 \
  --test_arg=--logtostderr=1 --test_arg=--v=0 \
  -- --logtostderr=1 --v=0 \
  > /tmp/zmq_repl_perf2.log 2>&1 &
REPL_PID2=$!
sleep 3
echo "REPL PID=${REPL_PID2}"

echo "=== perf record -F 99 -a -g (8s, system-wide) ==="
timeout 8 perf record -F 99 -a -g -o "${PERF_DATA}" 2>&1 || true
wait ${REPL_PID2} 2>/dev/null || true

echo
echo "=== perf report --stdio (top 60 lines) ==="
if [ -s "${PERF_DATA}" ]; then
  perf report --input "${PERF_DATA}" --stdio --no-child 2>&1 | head -60 > "${PERF_RECORD_OUT}"
  # Try to generate flamegraph if graphviz available
  # flamegraph.pl installed at ~/.local/bin (not in SSH PATH)
  if command -v /root/.local/bin/flamegraph.pl > /dev/null 2>&1; then
    perf script --input "${PERF_DATA}" 2>/dev/null | /root/.local/bin/flamegraph.pl --title="ZMQ RPC Latency REPL" > "${PERF_FG}" 2>&1 || true
  fi
  cat "${PERF_RECORD_OUT}"
else
  echo "perf.data is empty or missing" | tee "${PERF_RECORD_OUT}"
fi

echo
echo "=== Done. Files ==="
ls -lh "${PERF_STAT_OUT}" "${PERF_RECORD_OUT}" "${PERF_DATA}" "${PERF_FG}" 2>/dev/null || true
REMOTESCRIPT

REMOTE_RC=$?
echo
echo "=== SCP perf outputs back to ${LOCAL_RESULTS_DIR}/ ==="
scp "${REMOTE}:${PERF_STAT_REMOTE}" "${LOCAL_RESULTS_DIR}/perf_stat_report.txt" 2>/dev/null || echo "scp perf_stat failed"
scp "${REMOTE}:${PERF_RECORD_REMOTE}" "${LOCAL_RESULTS_DIR}/perf_record_report.txt" 2>/dev/null || echo "scp perf_record failed"
# Compress and transfer perf.data (may be large)
ssh "${REMOTE}" "gzip -c '${PERF_DATA_REMOTE}'" > "${LOCAL_RESULTS_DIR}/perf.data.gz" 2>/dev/null || echo "scp perf.data failed"
scp "${REMOTE}:${PERF_FLAME_REMOTE}" "${LOCAL_RESULTS_DIR}/" 2>/dev/null || echo "scp flamegraph failed"

echo
echo "=== Local results ==="
ls -lh "${LOCAL_RESULTS_DIR}"/perf_*.txt "${LOCAL_RESULTS_DIR}"/perf.data.gz "${LOCAL_RESULTS_DIR}"/flamegraph.svg 2>/dev/null || true

echo
if [ ${REMOTE_RC} -eq 0 ]; then
  echo "perf_profile done successfully."
else
  echo "perf_profile exited with code ${REMOTE_RC}."
fi
exit ${REMOTE_RC}
