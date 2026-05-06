#!/usr/bin/env bash
# Full profiling pipeline: runs all OS-level profiling scripts + existing REPL,
# then runs parse_profiling.py to produce a unified summary.
#
# Order:
#   1. tcp_profile.sh   — TCP stack metrics (retransmits, socket buffers)
#   2. syscall_profile.sh — strace -c (syscall time + call counts)
#   3. perf_profile.sh  — perf stat (hardware counters) + perf record (flamegraph)
#   4. repl_pipeline.sh  — existing REPL test (for 6 Histogram metrics)
#   5. parse_profiling.py — unified local parser
#
# Usage (from scripts/):
#   ./run_profiling_pipeline.sh              # all scripts, default 10s each
#   DURATION=15 ./run_profiling_pipeline.sh  # 15s per script
#   ./run_profiling_pipeline.sh --skip-perf  # skip perf (perf not installed)
#   ./run_profiling_pipeline.sh --skip-syscall  # skip strace

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=repl_remote_common.inc.sh
source "${SCRIPT_DIR}/repl_remote_common.inc.sh"

SKIP_TCP=0
SKIP_SYSCALL=0
SKIP_PERF=0
SKIP_REPL=0
SKIP_PARSE=0
DURATION="${DURATION:-10}"
PROFILING_RESULTS_DIR="${LOCAL_RESULTS_DIR}/profiling_$(date '+%Y%m%d_%H%M%S')"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-tcp)     SKIP_TCP=1 ;;
    --skip-syscall) SKIP_SYSCALL=1 ;;
    --skip-perf)    SKIP_PERF=1 ;;
    --skip-repl)    SKIP_REPL=1 ;;
    --skip-parse)   SKIP_PARSE=1 ;;
    -h|--help)
      sed -n '1,35p' "$0"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        DURATION="$1"
      else
        echo "Extra arg: $1" >&2
        exit 1
      fi
      ;;
  esac
  shift
done

mkdir -p "${PROFILING_RESULTS_DIR}"
export LOCAL_RESULTS_DIR="${PROFILING_RESULTS_DIR}"

echo "============================================================"
echo "ZMQ RPC Latency — Full Profiling Pipeline"
echo "============================================================"
echo "Remote:          ${REMOTE}"
echo "Remote DS:       ${REMOTE_DS}"
echo "DS OpenSource:   ${DS_OPENSOURCE_DIR_REMOTE}"
echo "Bazel jobs:      ${BAZEL_JOBS}"
echo "Duration/script: ${DURATION}s"
echo "Results dir:     ${PROFILING_RESULTS_DIR}"
echo ""
echo "Scripts to run:"
[[ "${SKIP_TCP}" -eq 0 ]] && echo "  [1] tcp_profile.sh"
[[ "${SKIP_SYSCALL}" -eq 0 ]] && echo "  [2] syscall_profile.sh"
[[ "${SKIP_PERF}" -eq 0 ]] && echo "  [3] perf_profile.sh"
[[ "${SKIP_REPL}" -eq 0 ]] && echo "  [4] repl_pipeline.sh"
[[ "${SKIP_PARSE}" -eq 0 ]] && echo "  [5] parse_profiling.py"
echo "============================================================"
echo

log_step() {
  echo ""
  echo "============================================================"
  echo "STEP: $1"
  echo "============================================================"
}

failed_steps=()

# --- Step 1: TCP profiling ---
if [[ "${SKIP_TCP}" -eq 0 ]]; then
  log_step "1/5 — TCP stack profiling (tcp_profile.sh)"
  if bash "${SCRIPT_DIR}/tcp_profile.sh" "${DURATION}"; then
    mv "${PROFILING_RESULTS_DIR}/tcp_profile_report.txt" "${PROFILING_RESULTS_DIR}/tcp_profile_report.txt" 2>/dev/null || true
    echo "✓ tcp_profile done"
  else
    echo "✗ tcp_profile FAILED (non-zero exit)"
    failed_steps+=("tcp_profile")
  fi
else
  echo "=== skipping tcp_profile (--skip-tcp) ==="
fi

# --- Step 2: Syscall profiling ---
if [[ "${SKIP_SYSCALL}" -eq 0 ]]; then
  log_step "2/5 — Syscall profiling (syscall_profile.sh)"
  if bash "${SCRIPT_DIR}/syscall_profile.sh" "${DURATION}"; then
    echo "✓ syscall_profile done"
  else
    echo "✗ syscall_profile FAILED (non-zero exit)"
    failed_steps+=("syscall_profile")
  fi
else
  echo "=== skipping syscall_profile (--skip-syscall) ==="
fi

# --- Step 3: Perf profiling ---
if [[ "${SKIP_PERF}" -eq 0 ]]; then
  log_step "3/5 — Perf profiling (perf_profile.sh)"
  if bash "${SCRIPT_DIR}/perf_profile.sh" "${DURATION}"; then
    echo "✓ perf_profile done"
  else
    echo "✗ perf_profile FAILED (non-zero exit) — perf likely not installed on remote"
    failed_steps+=("perf_profile")
  fi
else
  echo "=== skipping perf_profile (--skip-perf) ==="
fi

# --- Step 4: REPL baseline (for application metrics) ---
if [[ "${SKIP_REPL}" -eq 0 ]]; then
  log_step "4/5 — REPL baseline (repl_pipeline.sh)"
  # Run without parsing (we'll parse everything together at the end)
  if bash "${SCRIPT_DIR}/repl_pipeline.sh" --skip-parse "${DURATION}"; then
    # Move REPL log into profiling results dir
    if [[ -f "${LOCAL_RESULTS_DIR}/zmq_rpc_queue_latency_repl.log" ]]; then
      mv "${LOCAL_RESULTS_DIR}/zmq_rpc_queue_latency_repl.log" \
         "${PROFILING_RESULTS_DIR}/zmq_rpc_queue_latency_repl.log"
    fi
    echo "✓ repl done"
  else
    echo "✗ repl_pipeline FAILED (non-zero exit)"
    failed_steps+=("repl_pipeline")
  fi
else
  echo "=== skipping repl_pipeline (--skip-repl) ==="
fi

# --- Step 5: Unified parser ---
if [[ "${SKIP_PARSE}" -eq 0 ]]; then
  log_step "5/5 — Unified parser (parse_profiling.py)"
  if [[ -x "${SCRIPT_DIR}/parse_profiling.py" ]]; then
    python3 "${SCRIPT_DIR}/parse_profiling.py" "${PROFILING_RESULTS_DIR}"
    echo "✓ parse done"
  else
    echo "⚠ parse_profiling.py not found or not executable, skipping"
  fi
else
  echo "=== skipping parse (--skip-parse) ==="
fi

# --- Summary ---
echo ""
echo "============================================================"
echo "Pipeline Complete"
echo "============================================================"
echo "Results dir: ${PROFILING_RESULTS_DIR}"
echo ""
echo "Files collected:"
ls -lh "${PROFILING_RESULTS_DIR}/" 2>/dev/null || echo "  (empty)"
echo ""

if [[ ${#failed_steps[@]} -gt 0 ]]; then
  echo "FAILED steps: ${failed_steps[*]}"
  echo "These may be due to missing tools on the remote (see pre-flight checks)."
  echo "To re-run a specific step after installing tools:"
  echo "  tcp_profile.sh   -> ${SCRIPT_DIR}/tcp_profile.sh"
  echo "  syscall_profile.sh -> ${SCRIPT_DIR}/syscall_profile.sh"
  echo "  perf_profile.sh -> ${SCRIPT_DIR}/perf_profile.sh"
  echo "  repl_pipeline.sh -> ${SCRIPT_DIR}/repl_pipeline.sh"
else
  echo "✓ All steps succeeded."
fi

exit 0
