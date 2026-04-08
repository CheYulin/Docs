#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
# shellcheck source=../lib/vibe_coding_root.sh
. "${SCRIPT_DIR}/../lib/vibe_coding_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
FILTER="${FILTER:-KVClientExecutorRuntimeE2ETest.*}"
OUT_DIR="${VIBE_CODING_ROOT}/workspace/observability/strace"

usage() {
    cat <<'EOF'
Usage:
  bash scripts/perf/trace_kv_lock_io.sh [options]

Options:
  --build-dir <dir>   Build directory (default: ./build)
  --filter <expr>     GTest filter expression
  --out-dir <dir>     Output directory for strace artifacts (default: workspace/observability/strace)
  -h, --help          Show help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --filter)
            FILTER="$2"
            shift 2
            ;;
        --out-dir)
            OUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown arg: $1"
            usage
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

TEST_BIN="${BUILD_DIR}/tests/st/ds_st_kv_cache"
TEST_DESC="${BUILD_DIR}/tests/st/ds_st_kv_cache_tests.cmake"
[[ -x "${TEST_BIN}" ]] || { echo "Missing test binary: ${TEST_BIN}"; exit 1; }
[[ -f "${TEST_DESC}" ]] || { echo "Missing test descriptor: ${TEST_DESC}"; exit 1; }

mkdir -p "${OUT_DIR}"
TS="$(date +%Y%m%d_%H%M%S)"
TRACE_PREFIX="${OUT_DIR}/trace_${TS}"
SUMMARY_PATH="${OUT_DIR}/trace_${TS}_summary.json"
REPORT_PATH="${OUT_DIR}/trace_${TS}_report.md"

LD_PATH="$(
python3 - "${TEST_DESC}" "${TEST_BIN}" <<'PY'
import pathlib
import sys
text = pathlib.Path(sys.argv[1]).read_text(errors='ignore')
binary = sys.argv[2]
start = text.find("LD_LIBRARY_PATH=")
marker = f"]==] {binary}"
end = text.find(marker, start)
if start < 0 or end < 0:
    raise SystemExit(2)
print(text[start + len("LD_LIBRARY_PATH="):end], end="")
PY
)"

echo "[INFO] build_dir=${BUILD_DIR}"
echo "[INFO] filter=${FILTER}"
echo "[INFO] trace_prefix=${TRACE_PREFIX}"

LD_LIBRARY_PATH="${LD_PATH}" \
strace -ff -tt -T -s 128 -yy \
    -o "${TRACE_PREFIX}" \
    -e trace=futex,flock,fcntl,read,write,pread64,pwrite64,recvfrom,sendto,recvmsg,sendmsg,connect,accept,poll,ppoll,epoll_wait,epoll_pwait,mmap,munmap,nanosleep,clock_nanosleep \
    "${TEST_BIN}" --gtest_filter="${FILTER}" --gtest_color=no

python3 "${SCRIPT_DIR}/analyze_strace_lock_io.py" \
    --trace-prefix "${TRACE_PREFIX}" \
    --summary "${SUMMARY_PATH}" \
    --report "${REPORT_PATH}"

echo "[DONE] trace files prefix: ${TRACE_PREFIX}"
echo "[DONE] summary: ${SUMMARY_PATH}"
echo "[DONE] report: ${REPORT_PATH}"
