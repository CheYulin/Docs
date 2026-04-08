#!/usr/bin/env bash
# Collect lock-governance gate outputs (no sudo) into a timestamped directory for offline diff.
# Usage:
#   bash scripts/perf/collect_client_lock_baseline.sh [--build-dir DIR] [--out-root DIR] [--skip-perf] [-- ...extra args to validate_brpc_kv_executor.sh]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
OUT_ROOT="${ROOT_DIR}/plans/client_lock_baseline/runs"
RUN_PERF="on"
VALIDATE_EXTRA=()

usage() {
  cat <<'EOF'
Usage:
  bash scripts/perf/collect_client_lock_baseline.sh [options] [-- EXTRA_VALIDATE_ARGS...]

Options:
  --build-dir DIR     CMake build directory (default: ./build)
  --out-root DIR      Parent directory for run subdirs (default: plans/client_lock_baseline/runs)
  --skip-perf         Do not run kv_executor_perf_analysis.py (E2E cluster may be required)
  -h, --help          This help

After "--", remaining args are passed to scripts/verify/validate_brpc_kv_executor.sh

Each run creates:
  <out-root>/<YYYYMMDD_HHMMSS>_<githash>/
    RUN_META.txt       host, user, git sha, cmake marker
    gate_validate.log  full stdout/stderr of validate_brpc_kv_executor.sh
    gate_exit.code     exit code of validate script
    perf/              optional; kv_executor_perf_analysis outputs if perf succeeded
    perf_exit.code     exit code of perf script (0=ok, 77=skipped, non-zero=failed)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir)
      BUILD_DIR="$2"
      shift 2
      ;;
    --out-root)
      OUT_ROOT="$2"
      shift 2
      ;;
    --skip-perf)
      RUN_PERF="off"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      VALIDATE_EXTRA=("$@")
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

mkdir -p "${OUT_ROOT}"
GIT_SHORT="$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo nogit)"
RUN_ID="$(date +%Y%m%d_%H%M%S)_${GIT_SHORT}"
RUN_DIR="${OUT_ROOT}/${RUN_ID}"
mkdir -p "${RUN_DIR}"

{
  echo "run_id=${RUN_ID}"
  echo "collected_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname 2>/dev/null || echo unknown)"
  echo "user=${USER:-unknown}"
  echo "root_dir=${ROOT_DIR}"
  echo "build_dir=${BUILD_DIR}"
  echo "git_sha_full=$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "git_short=${GIT_SHORT}"
  if [[ -f "${BUILD_DIR}/CMakeCache.txt" ]]; then
    echo "cmake_generator=$(grep '^CMAKE_GENERATOR:INTERNAL=' "${BUILD_DIR}/CMakeCache.txt" | cut -d= -f2- || true)"
  else
    echo "cmake_generator=(no CMakeCache.txt)"
  fi
} > "${RUN_DIR}/RUN_META.txt"

echo "[INFO] Writing gate logs to ${RUN_DIR}"

set +e
bash "${SCRIPT_DIR}/../verify/validate_brpc_kv_executor.sh" \
  --build-dir "${BUILD_DIR}" \
  "${VALIDATE_EXTRA[@]}" \
  >"${RUN_DIR}/gate_validate.log" 2>&1
GATE_RC=$?
set -e
echo "${GATE_RC}" > "${RUN_DIR}/gate_exit.code"

PERF_RC=77
if [[ "${RUN_PERF}" == "on" && -x "${BUILD_DIR}/tests/st/ds_st_kv_cache" ]]; then
  PERF_DIR="${RUN_DIR}/perf"
  mkdir -p "${PERF_DIR}"
  set +e
  python3 "${SCRIPT_DIR}/kv_executor_perf_analysis.py" \
    --build-dir "${BUILD_DIR}" \
    --runs 3 \
    --ops 80 \
    --warmup 15 \
    --output-dir "${PERF_DIR}" \
    >"${RUN_DIR}/perf_stdout.log" 2>"${RUN_DIR}/perf_stderr.log"
  PERF_RC=$?
  set -e
else
  echo "[INFO] Skipping kv_executor_perf_analysis (skip flag or missing ${BUILD_DIR}/tests/st/ds_st_kv_cache)" | tee -a "${RUN_DIR}/gate_validate.log"
fi
echo "${PERF_RC}" > "${RUN_DIR}/perf_exit.code"

{
  echo "=== SUMMARY (for scripts/diff) ==="
  echo "gate_exit.code=${GATE_RC}"
  echo "perf_exit.code=${PERF_RC}  # 77 means skipped"
  if [[ -f "${RUN_DIR}/perf/kv_executor_perf_summary.txt" ]]; then
    echo "--- perf absolute latency us_mean (acceptance) ---"
    grep -E '^(inline|injected)_(set|get)_avg_us_mean=' "${RUN_DIR}/perf/kv_executor_perf_summary.txt" || true
    echo "--- perf summary (tail) ---"
    tail -n 25 "${RUN_DIR}/perf/kv_executor_perf_summary.txt"
  fi
  echo "--- gate last 30 lines ---"
  tail -n 30 "${RUN_DIR}/gate_validate.log"
} > "${RUN_DIR}/SUMMARY.txt"

echo "[DONE] Run directory: ${RUN_DIR}"
echo "[DONE] Gate exit code: ${GATE_RC} (see gate_exit.code)"
echo "[DONE] Perf exit code: ${PERF_RC} (see perf_exit.code; 77=skipped)"
