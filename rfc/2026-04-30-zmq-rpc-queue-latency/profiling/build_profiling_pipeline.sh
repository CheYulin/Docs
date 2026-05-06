#!/usr/bin/env bash
# =============================================================================
# build_profiling_pipeline.sh — Build datasystem with optimal profiling config,
# then run all OS-level profiling scripts + REPL baseline.
#
# Build:  build.sh -b bazel -r -p on -t build
#          (-r = release, -p on = ENABLE_PERF, -t build = compile tests)
#          -> -O2 -DNDEBUG -DENABLE_PERF -g3
#
# Profiling suite:
#   tcp_profile.sh      TCP stack (retransmits, socket buffers, ss -ti)
#   syscall_profile.sh  strace -c (syscall time + call counts)  [needs strace on remote]
#   perf_profile.sh     perf stat -a (hw counters, 1s interval)
#                       perf record -F 99 -a -g (flamegraph, 99Hz system-wide)
#   repl_pipeline.sh    REPL baseline (application metrics: 6 Histograms)
#
# Usage (from profiling/):
#   ./build_profiling_pipeline.sh                     # build + all profiles (10s each)
#   DURATION=15 ./build_profiling_pipeline.sh           # 15s per script
#   ./build_profiling_pipeline.sh --skip-build          # reuse last build
#   ./build_profiling_pipeline.sh --skip-tcp           # skip TCP profile
#   ./build_profiling_pipeline.sh --skip-perf          # skip perf (perf not installed)
#   ./build_profiling_pipeline.sh --skip-syscall       # skip strace
#   ./build_profiling_pipeline.sh --skip-repl           # skip REPL baseline
#   ./build_profiling_pipeline.sh --skip-parse          # skip parse step
#
# Environment (override before running):
#   REMOTE_USER   SSH user (default: root)
#   REMOTE_HOST   SSH host (default: xqyun-32c32g)
#   DURATION      Test duration per profiling script (default: 10 seconds)
#   BAZEL_JOBS   Parallel build jobs (default: 32)
#   BAZEL_BUILD_STEPS  What to build: "build" (default) or "build_and_test"
#
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/ holds rsync_datasystem.sh (stayed in scripts/); profiling/ holds the rest
SCRIPTS_DIR="$(cd "${SCRIPT_DIR}/../scripts" && pwd)"
# shellcheck source=repl_remote_common.inc.sh
source "${SCRIPT_DIR}/repl_remote_common.inc.sh"

# ----- Option parsing -----
SKIP_SYNC=0
SKIP_BUILD=0
SKIP_TCP=0
SKIP_SYSCALL=0
SKIP_PERF=0
SKIP_REPL=0
SKIP_PARSE=0
DURATION="${DURATION:-10}"
BAZEL_BUILD_STEPS="${BAZEL_BUILD_STEPS:-build}"  # "build" or "build_and_test"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-sync)    SKIP_SYNC=1 ;;
    --skip-build)   SKIP_BUILD=1 ;;
    --skip-tcp)     SKIP_TCP=1 ;;
    --skip-syscall) SKIP_SYSCALL=1 ;;
    --skip-perf)    SKIP_PERF=1 ;;
    --skip-repl)    SKIP_REPL=1 ;;
    --skip-parse)   SKIP_PARSE=1 ;;
    --build-and-test) BAZEL_BUILD_STEPS="build_and_test" ;;
    -h|--help)
      sed -n '1,40p' "$0"
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

# ----- Results directory -----
PROFILING_DIR="${LOCAL_RESULTS_DIR}/profiling_$(date '+%Y%m%d_%H%M%S')"
mkdir -p "${PROFILING_DIR}"
export LOCAL_RESULTS_DIR="${PROFILING_DIR}"

echo "============================================================"
echo "Build + Profiling Pipeline"
echo "============================================================"
echo "Remote:        ${REMOTE}"
echo "Remote DS:     ${REMOTE_DS}"
echo "DS OpenSource: ${DS_OPENSOURCE_DIR_REMOTE}"
echo "Bazel jobs:    ${BAZEL_JOBS}"
echo "Build steps:   ${BAZEL_BUILD_STEPS}"
echo "Duration/script: ${DURATION}s"
echo "Results dir:   ${PROFILING_DIR}"
echo ""
echo "Steps:"
[[ "${SKIP_SYNC}" -eq 0 ]]   && echo "  [1] rsync local DS -> remote"
[[ "${SKIP_BUILD}" -eq 0 ]]  && echo "  [2] build.sh -b bazel -r -p on -t ${BAZEL_BUILD_STEPS}"
[[ "${SKIP_TCP}" -eq 0 ]]   && echo "  [3] tcp_profile.sh"
[[ "${SKIP_SYSCALL}" -eq 0 ]] && echo "  [4] syscall_profile.sh"
[[ "${SKIP_PERF}" -eq 0 ]]  && echo "  [5] perf_profile.sh"
[[ "${SKIP_REPL}" -eq 0 ]]  && echo "  [6] repl_pipeline.sh"
[[ "${SKIP_PARSE}" -eq 0 ]] && echo "  [7] parse_profiling.py"
echo "============================================================"
echo

failed_steps=()
step_num=0

# ----- Helper -----
log_step() {
  echo ""
  echo "============================================================"
  echo "STEP $1: $2"
  echo "============================================================"
}

run_step() {
  local name="$1"; shift
  local cmd="$1"; shift
  echo ">>> Running: ${cmd}"
  if eval "${cmd}" 2>&1; then
    echo "✓ ${name} succeeded"
    return 0
  else
    local rc=$?
    echo "✗ ${name} failed (exit ${rc})"
    return ${rc}
  fi
}

# ----- Step 1: Rsync -----
if [[ "${SKIP_SYNC}" -eq 0 ]]; then
  ((step_num++)) || true
  log_step "${step_num}/7" "Rsync local DS -> remote"
  if ! bash "${SCRIPTS_DIR}/rsync_datasystem.sh"; then
    failed_steps+=("rsync")
  fi
else
  echo "=== skipping rsync (--skip-sync) ==="
fi

# ----- Step 2: Build -----
if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  ((step_num++)) || true
  log_step "${step_num}/7" "Build with build.sh -b bazel -r -p on -t ${BAZEL_BUILD_STEPS}"

  BUILD_TARGET="build"
  if [[ "${BAZEL_BUILD_STEPS}" == "build_and_test" ]]; then
    BUILD_TARGET="build_and_test"
  fi

  # Use the project build.sh (not bare bazel) for consistent flags:
  #   -b bazel -r = release (-O2 -DNDEBUG -g3)
  #   -p on    = --config=perf (-DENABLE_PERF)
  #   -t <step>= build = compile tests (including zmq_rpc_queue_latency_repl)
  build_cmd="ssh '${REMOTE}' bash -s '${REMOTE_DS}' '${DS_OPENSOURCE_DIR_REMOTE}' '${BAZEL_JOBS}' '${BUILD_TARGET}' <<'REMOTESCRIPT'
set -euo pipefail
REMOTE_DS="\$1"
DS_OP="\$2"
JOBS="\$3"
BUILD_STEP="\$4"
export DS_OPENSOURCE_DIR="\${DS_OP}"
mkdir -p "\${DS_OP}"
cd "\${REMOTE_DS}"
echo "=== build.sh -b bazel -r -p on -t \${BUILD_STEP} -j \${JOBS} ==="
echo "DS_OPENSOURCE_DIR=\${DS_OP}"
bash build.sh -b bazel -r -p on -t "\${BUILD_STEP}" -j "\${JOBS}"
echo "=== build complete ==="
REMOTESCRIPT"

  if ! eval "${build_cmd}"; then
    failed_steps+=("build")
  fi
else
  echo "=== skipping build (--skip-build) ==="
fi

# ----- Step 3-6: Profiling scripts -----
# These all source repl_remote_common.inc.sh and need LOCAL_RESULTS_DIR set.

if [[ "${SKIP_TCP}" -eq 0 ]]; then
  ((step_num++)) || true
  log_step "${step_num}/7" "TCP stack profiling (tcp_profile.sh)"
  export LOCAL_RESULTS_DIR="${PROFILING_DIR}"
  if ! bash "${SCRIPT_DIR}/tcp_profile.sh" "${DURATION}"; then
    failed_steps+=("tcp_profile")
  fi
else
  echo "=== skipping tcp_profile (--skip-tcp) ==="
fi

if [[ "${SKIP_SYSCALL}" -eq 0 ]]; then
  ((step_num++)) || true
  log_step "${step_num}/7" "Syscall profiling (syscall_profile.sh)"
  export LOCAL_RESULTS_DIR="${PROFILING_DIR}"
  if ! bash "${SCRIPT_DIR}/syscall_profile.sh" "${DURATION}"; then
    failed_steps+=("syscall_profile")
  fi
else
  echo "=== skipping syscall_profile (--skip-syscall) ==="
fi

if [[ "${SKIP_PERF}" -eq 0 ]]; then
  ((step_num++)) || true
  log_step "${step_num}/7" "Perf profiling (perf_profile.sh)"
  export LOCAL_RESULTS_DIR="${PROFILING_DIR}"
  if ! bash "${SCRIPT_DIR}/perf_profile.sh" "${DURATION}"; then
    failed_steps+=("perf_profile")
  fi
else
  echo "=== skipping perf_profile (--skip-perf) ==="
fi

if [[ "${SKIP_REPL}" -eq 0 ]]; then
  ((step_num++)) || true
  log_step "${step_num}/7" "REPL baseline (repl_pipeline.sh)"
  export LOCAL_RESULTS_DIR="${PROFILING_DIR}"
  if ! bash "${SCRIPT_DIR}/repl_pipeline.sh" --skip-parse "${DURATION}"; then
    failed_steps+=("repl_pipeline")
  fi
  # Move repl log into profiling dir
  if [[ -f "${PROFILING_DIR}/zmq_rpc_queue_latency_repl.log" ]]; then
    : # already there
  elif [[ -f "${LOCAL_RESULTS_DIR}/zmq_rpc_queue_latency_repl.log" ]]; then
    mv "${LOCAL_RESULTS_DIR}/zmq_rpc_queue_latency_repl.log" "${PROFILING_DIR}/"
  fi
else
  echo "=== skipping repl_pipeline (--skip-repl) ==="
fi

# ----- Step 7: Parse -----
if [[ "${SKIP_PARSE}" -eq 0 ]]; then
  ((step_num++)) || true
  log_step "${step_num}/7" "Parse results (parse_profiling.py)"
  python3 "${SCRIPT_DIR}/parse_profiling.py" "${PROFILING_DIR}"
else
  echo "=== skipping parse (--skip-parse) ==="
fi

# ----- Summary -----
echo ""
echo "============================================================"
echo "Pipeline Complete"
echo "============================================================"
echo "Results: ${PROFILING_DIR}"
echo ""
echo "Files:"
ls -lh "${PROFILING_DIR}/" 2>/dev/null || echo "  (empty)"
echo ""

if [[ ${#failed_steps[@]} -gt 0 ]]; then
  echo "FAILED: ${failed_steps[*]}"
  echo ""
  echo "Common causes:"
  echo "  - perf_profile: perf not installed on remote → dnf install -y perf"
  echo "  - syscall_profile: strace not installed → dnf install -y strace"
  echo "  - tcp_profile: ss/iproute missing → dnf install -y iproute"
  echo "  - build: third-party cache mismatch → rm -f \${REMOTE_DS}/bazel-*/*/CMakeCache.txt"
  exit 1
else
  echo "✓ All steps succeeded."
  exit 0
fi
