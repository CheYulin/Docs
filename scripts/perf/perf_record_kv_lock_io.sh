#!/usr/bin/env bash
# Record dwarf call graphs for ds_st_kv_cache (often better symbols than raw bpftrace ustack).
#
# Usage (repo root):
#   bash scripts/perf/perf_record_kv_lock_io.sh [--build-dir build] [--out datafile]
#
# Then:
#   perf report -i <datafile> --no-children
#
# Requires: perf, debug-friendly build (RelWithDebInfo + -g -fno-omit-frame-pointer).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
# shellcheck source=../lib/vibe_coding_root.sh
. "${SCRIPT_DIR}/../lib/vibe_coding_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
OUT_DATA="${VIBE_CODING_ROOT}/workspace/observability/perf/kv_lock_io.perf.data"
FILTER="${FILTER:-KVClientExecutorRuntimeE2ETest.*}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir) BUILD_DIR="$2"; shift 2 ;;
        --out) OUT_DATA="$2"; shift 2 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

[[ "${BUILD_DIR}" != /* ]] && BUILD_DIR="${ROOT_DIR}/${BUILD_DIR}"
[[ "${OUT_DATA}" != /* ]] && OUT_DATA="${VIBE_CODING_ROOT}/${OUT_DATA}"

TEST_BIN="${BUILD_DIR}/tests/st/ds_st_kv_cache"
TEST_DESC="${BUILD_DIR}/tests/st/ds_st_kv_cache_tests.cmake"
[[ -x "${TEST_BIN}" ]] || { echo "Missing: ${TEST_BIN}"; exit 1; }
[[ -f "${TEST_DESC}" ]] || { echo "Missing: ${TEST_DESC}"; exit 1; }

command -v perf >/dev/null || { echo "Install linux-tools / perf"; exit 1; }

LD_PATH="$(
python3 - "${TEST_DESC}" "${TEST_BIN}" <<'PY'
import pathlib, sys
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

mkdir -p "$(dirname "${OUT_DATA}")"

echo "[INFO] perf record (dwarf) -> ${OUT_DATA}"
echo "[INFO] filter=${FILTER}"

# dwarf + reasonable stack size; user may need: sysctl kernel.perf_event_paranoid=-1
perf record -g \
    --call-graph dwarf,16384 \
    -o "${OUT_DATA}" \
    -- env LD_LIBRARY_PATH="${LD_PATH}" \
    "${TEST_BIN}" --gtest_filter="${FILTER}" --gtest_color=no

echo "[DONE] perf.data: ${OUT_DATA}"
echo "[NEXT] perf report -i ${OUT_DATA} --no-children"
