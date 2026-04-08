#!/usr/bin/env bash
# Simple 3-step workflow:
# 1) correctness check (non-sudo)
# 2) print sudo capture command for manual run
# 3) analyze (non-sudo)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
# shellcheck source=../lib/vibe_coding_root.sh
. "${SCRIPT_DIR}/../lib/vibe_coding_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
OUT_DIR="${VIBE_CODING_ROOT}/workspace/observability/bpftrace"
FILTER="KVClientExecutorRuntimeE2ETest.PerfConcurrentMCreateMSetMGetExistUnderContention"
BASELINE_TRACE=""
CURRENT_TRACE=""
SKIP_CHECK=0

usage() {
  cat <<'EOF'
Usage:
  bash scripts/perf/run_kv_lock_ebpf_workflow.sh [options]

Options:
  --build-dir <dir>      Build directory (default: ./build)
  --out-dir <dir>        Trace output directory (default: workspace/observability/bpftrace)
  --filter <expr>        GTest filter (default: PerfConcurrent...UnderContention)
  --baseline <file>      Optional baseline trace file for A/B compare
  --current <file>       Current trace file for analysis
  --skip-check           Skip correctness check step
  -h, --help             Show help

Flow:
  Step 1 (auto): run non-sudo correctness check
  Step 2 (manual): run printed sudo command for capture
  Step 3 (auto): run analysis script on current/baseline traces
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir)
      BUILD_DIR="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --filter)
      FILTER="$2"
      shift 2
      ;;
    --baseline)
      BASELINE_TRACE="$2"
      shift 2
      ;;
    --current)
      CURRENT_TRACE="$2"
      shift 2
      ;;
    --skip-check)
      SKIP_CHECK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "${BUILD_DIR}" != /* ]]; then
  BUILD_DIR="${ROOT_DIR}/${BUILD_DIR}"
fi
if [[ "${OUT_DIR}" != /* ]]; then
  OUT_DIR="${VIBE_CODING_ROOT}/${OUT_DIR}"
fi
if [[ -n "${BASELINE_TRACE}" && "${BASELINE_TRACE}" != /* ]]; then
  BASELINE_TRACE="${VIBE_CODING_ROOT}/${BASELINE_TRACE}"
fi
if [[ -n "${CURRENT_TRACE}" && "${CURRENT_TRACE}" != /* ]]; then
  CURRENT_TRACE="${VIBE_CODING_ROOT}/${CURRENT_TRACE}"
fi

echo "========== Step 1: Correctness check (non-sudo) =========="
if [[ "${SKIP_CHECK}" -eq 0 ]]; then
  bash "${SCRIPT_DIR}/run_kv_concurrent_lock_perf.sh" "${BUILD_DIR}"
else
  echo "[SKIP] --skip-check set"
fi

echo
echo "========== Step 2: Capture (manual sudo) =========="
echo "Run this command manually:"
echo
echo "sudo bash \"${SCRIPT_DIR}/trace_kv_lock_io_bpftrace.sh\" \\"
echo "  --build-dir \"${BUILD_DIR}\" \\"
echo "  --out-dir \"${OUT_DIR}\" \\"
echo "  --filter '${FILTER}'"
echo
echo "After it finishes, re-run this workflow with --current <trace_file> to analyze."

if [[ -z "${CURRENT_TRACE}" ]]; then
  exit 0
fi

if [[ ! -f "${CURRENT_TRACE}" ]]; then
  echo "Missing --current file: ${CURRENT_TRACE}" >&2
  exit 2
fi

echo
echo "========== Step 3: Analyze (non-sudo) =========="
if [[ -n "${BASELINE_TRACE}" ]]; then
  if [[ ! -f "${BASELINE_TRACE}" ]]; then
    echo "Missing --baseline file: ${BASELINE_TRACE}" >&2
    exit 2
  fi
  python3 "${SCRIPT_DIR}/analyze_kv_lock_bpftrace.py" \
    --baseline "${BASELINE_TRACE}" \
    --current "${CURRENT_TRACE}"
else
  python3 "${SCRIPT_DIR}/analyze_kv_lock_bpftrace.py" \
    --current "${CURRENT_TRACE}"
fi
