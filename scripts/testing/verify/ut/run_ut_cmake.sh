#!/usr/bin/env bash
# Unit test regression using CMake (< 30 minutes).
#
# Usage:
#   bash scripts/testing/verify/ut/run_ut_cmake.sh [--skip-build] [--ctest-args <args>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"
BUILD_DIR="${DS_ROOT}/build"

SKIP_BUILD=0
CTEST_ARGS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    --ctest-args) CTEST_ARGS="$2"; shift 2 ;;
    *) shift ;;
  esac
done

cd "${DS_ROOT}"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "Building with CMake..."
  bash build.sh -t build -B "${BUILD_DIR}" -b cmake -j "${JOBS:-$(nproc)}" 2>&1 | tail -5
fi

echo "Running UT regression..."
ctest --test-dir "${BUILD_DIR}" \
  --output-on-failure \
  -R "ut|UT|unit" \
  -j "${JOBS:-$(nproc)}" \
  ${CTEST_ARGS} 2>&1 | tail -30

echo "UT regression done"
