#!/usr/bin/env bash
# Pure CMake build entry point.
# Delegates to yuanrong-datasystem/build.sh -b cmake.
#
# Usage:
#   bash scripts/build/build_cmake.sh [-j <jobs>] [-t build|run_example|...]
#
# Environment:
#   JOBS         - parallel jobs (default: nproc)
#   BUILD_DIR    - build directory (default: build/)
#   DS_ROOT      - yuanrong-datasystem root (default: resolved from this script)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DS_ROOT:-$(cd "${SCRIPT_DIR}/../../yuanrong-datasystem" 2>/dev/null && pwd)}"

if [[ ! -d "${DS_ROOT}" ]]; then
  echo "DS_ROOT not found. Set DS_ROOT or run from yuanrong-datasystem-agent-workbench/" >&2
  exit 1
fi

cd "${DS_ROOT}"

JOBS="${JOBS:-$(nproc)}"
BUILD_DIR="${BUILD_DIR:-build}"
TASK="${1:-build}"

exec bash build.sh -b cmake -t "${TASK}" -B "${BUILD_DIR}" -j "${JOBS}" "${@:2}"
