#!/usr/bin/env bash
# Build backend abstraction: dispatches between CMake and Bazel.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/build_backend.sh"
#
#   BUILD_BACKEND=cmake    # or bazel
#   DS_ROOT=/path/to/ds
#
#   build_cmd          - print the build command (echoes, does not run)
#   build_run_cmd      - print the run/test command
#   build_binary_path  - print the path to a built binary

set -euo pipefail

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing build_backend.sh}"
: "${BUILD_BACKEND:?BUILD_BACKEND must be set (cmake or bazel)}"
: "${DS_ROOT:?DS_ROOT must be set}"

build_cmd() {
  case "${BUILD_BACKEND}" in
    cmake)
      echo "cmake --build '${DS_ROOT}/build' --parallel \${JOBS:-}"
      ;;
    bazel)
      echo "bazel build \${BAZEL_TARGETS:-//...}"
      ;;
    *)
      echo "Unknown BUILD_BACKEND=${BUILD_BACKEND}" >&2
      return 1
      ;;
  esac
}

# Run a specific test target.
# Usage: build_run_cmd <target_name> [gtest_filter]
build_run_cmd() {
  local target="${1:?build_run_cmd: target name required}"
  local filter="${2:-}"
  case "${BUILD_BACKEND}" in
    cmake)
      if [[ -n "$filter" ]]; then
        echo "ctest --test-dir '${DS_ROOT}/build' -R '${target}' --output-on-failure --parallel \${JOBS:-} -L '${filter}'"
      else
        echo "ctest --test-dir '${DS_ROOT}/build' -R '${target}' --output-on-failure --parallel \${JOBS:-}"
      fi
      ;;
    bazel)
      if [[ -n "$filter" ]]; then
        echo "bazel run \${BAZEL_TARGETS:-//${target}} --test_filter='${filter}'"
      else
        echo "bazel run \${BAZEL_TARGETS:-//${target}}"
      fi
      ;;
  esac
}

# Print the path to a built binary.
build_binary_path() {
  local binary_name="${1:?build_binary_path: binary name required}"
  case "${BUILD_BACKEND}" in
    cmake)
      echo "${DS_ROOT}/build/bin/${binary_name}"
      ;;
    bazel)
      echo "${DS_ROOT}/bazel-bin/${binary_name}"
      ;;
  esac
}
