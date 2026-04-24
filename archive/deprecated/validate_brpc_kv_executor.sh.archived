#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../development/lib/datasystem_root.sh
. "${SCRIPT_DIR}/../../development/lib/datasystem_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
OUT_DIR="${ROOT_DIR}/.third_party/brpc_st_compat"
JOBS="${JOBS:-$(nproc)}"
FILTER="${FILTER:-KVClientBrpcBthreadReferenceTest.*}"
FEATURE_FILTER="${FEATURE_FILTER:-KVClientBrpcBthreadReferenceTest.*:KVClientExecutorRuntimeE2ETest.*}"
RUN_BOOTSTRAP="on"
RUN_BUILD="on"
RUN_TEST="on"
RUN_COVERAGE_HTML="off"
COVERAGE_OUT_DIR=""

usage() {
    cat <<'EOF'
Usage:
  bash scripts/verify/validate_brpc_kv_executor.sh [options]

Options:
  --build-dir <dir>        Build directory (default: ./build)
  --out-dir <dir>          brpc compat output root (default: ./.third_party/brpc_st_compat)
  --jobs <n>               Parallel jobs (default: nproc)
  --filter <gtest_filter>  Test filter regex (default: KVClientBrpcBthreadReferenceTest.*)
  --feature-filter <expr>  Feature test filter for coverage run
                           (default: KVClientBrpcBthreadReferenceTest.*:KVClientExecutorRuntimeE2ETest.*)
  --coverage-html          Generate focused feature coverage HTML after tests
  --coverage-out-dir <dir> Coverage output directory
                           (default: <build-dir>/coverage_kvexec)
  --skip-bootstrap         Skip bootstrap_brpc_st_compat.sh
  --skip-build             Skip cmake configure/build
  --skip-test              Skip ctest run
  -h, --help               Show help
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
        --jobs)
            JOBS="$2"
            shift 2
            ;;
        --filter)
            FILTER="$2"
            shift 2
            ;;
        --feature-filter)
            FEATURE_FILTER="$2"
            shift 2
            ;;
        --coverage-html)
            RUN_COVERAGE_HTML="on"
            shift
            ;;
        --coverage-out-dir)
            COVERAGE_OUT_DIR="$2"
            shift 2
            ;;
        --skip-bootstrap)
            RUN_BOOTSTRAP="off"
            shift
            ;;
        --skip-build)
            RUN_BUILD="off"
            shift
            ;;
        --skip-test)
            RUN_TEST="off"
            shift
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

if [[ -z "${COVERAGE_OUT_DIR}" ]]; then
    COVERAGE_OUT_DIR="${BUILD_DIR}/coverage_kvexec"
fi

echo "[INFO] ROOT_DIR=${ROOT_DIR}"
echo "[INFO] BUILD_DIR=${BUILD_DIR}"
echo "[INFO] OUT_DIR=${OUT_DIR}"
echo "[INFO] JOBS=${JOBS}"
echo "[INFO] FILTER=${FILTER}"
echo "[INFO] FEATURE_FILTER=${FEATURE_FILTER}"
echo "[INFO] RUN_COVERAGE_HTML=${RUN_COVERAGE_HTML}"
echo "[INFO] COVERAGE_OUT_DIR=${COVERAGE_OUT_DIR}"

run_feature_tests_direct() {
    local test_binary="${BUILD_DIR}/tests/st/ds_st_kv_cache"
    local test_desc="${BUILD_DIR}/tests/st/ds_st_kv_cache_tests.cmake"
    if [[ ! -x "${test_binary}" || ! -f "${test_desc}" ]]; then
        echo "[ERROR] Missing test binary or descriptor under ${BUILD_DIR}/tests/st"
        exit 1
    fi
    local ld_path
    ld_path="$(
        python3 - "${test_desc}" "${test_binary}" <<'PY'
import pathlib
import sys
text = pathlib.Path(sys.argv[1]).read_text(errors='ignore')
binary = sys.argv[2]
start = text.find("LD_LIBRARY_PATH=")
marker = f"]==] {binary}"
end = text.find(marker, start)
if start < 0 or end < 0:
    raise SystemExit(2)
print(text[start + len("LD_LIBRARY_PATH="):end], end='')
PY
    )"
    echo "[STEP] Run feature tests directly for coverage collection"
    LD_LIBRARY_PATH="${ld_path}" "${test_binary}" --gtest_filter="${FEATURE_FILTER}" --gtest_color=no
}

generate_feature_coverage_html() {
    local info_dir="${COVERAGE_OUT_DIR}/.info"
    mkdir -p "${info_dir}"
    echo "[STEP] Reset gcov counters"
    lcov --zerocounters --directory "${BUILD_DIR}"
    run_feature_tests_direct
    echo "[STEP] Capture focused coverage info"
    lcov --rc lcov_branch_coverage=1 \
        --ignore-errors mismatch,gcov,source,negative \
        -c -d "${BUILD_DIR}" -o "${info_dir}/raw_all.info"
    lcov --rc lcov_branch_coverage=1 \
        --ignore-errors mismatch,source,negative \
        --extract "${info_dir}/raw_all.info" \
        "*/src/datasystem/client/kv_cache/kv_client.cpp" \
        "*/src/datasystem/client/kv_cache/kv_executor.cpp" \
        "*/tests/st/client/kv_cache/kv_client_brpc_bthread_reference_test.cpp" \
        -o "${info_dir}/feature.info"
    genhtml --branch-coverage --ignore-errors source \
        -t "kv executor brpc feature" \
        -o "${COVERAGE_OUT_DIR}" "${info_dir}/feature.info"
    echo "[DONE] Coverage HTML generated: ${COVERAGE_OUT_DIR}/index.html"
}

if [[ "${RUN_BOOTSTRAP}" == "on" ]]; then
    echo "[STEP] Bootstrap brpc compatibility toolchain"
    "${SCRIPT_DIR}/../../build/bootstrap_brpc_st_compat.sh" \
        --build-dir "${BUILD_DIR}" \
        --out-dir "${OUT_DIR}" \
        --jobs "${JOBS}"
fi

if [[ "${RUN_BUILD}" == "on" ]]; then
    echo "[STEP] Configure and build kv cache ST target"
    cmake -S "${ROOT_DIR}" -B "${BUILD_DIR}" \
        -DENABLE_BRPC_ST_REFERENCE=ON \
        -DBRPC_ST_ROOT="${OUT_DIR}/install"

    env -u CPLUS_INCLUDE_PATH -u CPATH -u LIBRARY_PATH -u LD_LIBRARY_PATH \
        cmake --build "${BUILD_DIR}" --target ds_st_kv_cache -j "${JOBS}"
fi

if [[ "${RUN_TEST}" == "on" ]]; then
    echo "[STEP] Run brpc+bthread kv deadlock contrast tests"
    ctest --test-dir "${BUILD_DIR}" --output-on-failure -R "${FILTER}"
fi

if [[ "${RUN_COVERAGE_HTML}" == "on" ]]; then
    generate_feature_coverage_html
fi

echo "[DONE] brpc executor injection validation flow completed."
