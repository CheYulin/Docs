#!/usr/bin/env bash
# Smoke test using CMake (< 5 minutes).
# Runs a fast subset of tests to verify basic correctness.
#
# Usage:
#   bash scripts/testing/verify/smoke/run_smoke_cmake.sh [--skip-build]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"
BUILD_DIR="${DS_ROOT}/build"

SKIP_BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    *) shift ;;
  esac
done

cd "${DS_ROOT}"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "Building with CMake..."
  bash build.sh -t build -B "${BUILD_DIR}" -b cmake -j "${JOBS:-$(nproc)}" 2>&1 | tail -5
fi

echo "Running smoke tests..."
ctest --test-dir "${BUILD_DIR}" \
  --output-on-failure \
  -R smoke \
  -j "${JOBS:-$(nproc)}" 2>&1 | tail -30

echo "Smoke test done"
