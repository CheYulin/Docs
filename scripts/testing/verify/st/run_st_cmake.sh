#!/usr/bin/env bash
# Integration test (ST) using CMake (< 60 minutes).
#
# Usage:
#   bash scripts/testing/verify/st/run_st_cmake.sh [--skip-build] [--ctest-args <args>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"
BUILD_DIR="${DS_ROOT}/build"

SKIP_BUILD=0

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

echo "Running ST integration tests..."
ctest --test-dir "${BUILD_DIR}" \
  --output-on-failure \
  -R "st|ST|integration" \
  -j "${JOBS:-$(nproc)}" \
  ${CTEST_ARGS} 2>&1 | tail -30

echo "ST done"
