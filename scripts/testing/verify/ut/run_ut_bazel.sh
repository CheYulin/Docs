#!/usr/bin/env bash
# Unit test regression using Bazel (< 30 minutes).
#
# Usage:
#   bash scripts/testing/verify/ut/run_ut_bazel.sh [--skip-build] [--test-filter <gtest_filter>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"

SKIP_BUILD=0
FILTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    --test-filter) FILTER="$2"; shift 2 ;;
    *) shift ;;
  esac
done

cd "${DS_ROOT}"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "Building UT targets with Bazel..."
  bazel build //tests/... 2>&1 | tail -5
fi

echo "Running UT regression..."
if [[ -n "${FILTER}" ]]; then
  bazel test //tests/... --test_filter="${FILTER}" --test_output=errors --jobs="${JOBS:-$(nproc)}" 2>&1 | tail -30
else
  bazel test //tests/... --test_tag_filters=ut,UT --test_output=errors --jobs="${JOBS:-$(nproc)}" 2>&1 | tail -30
fi

echo "UT regression done"
