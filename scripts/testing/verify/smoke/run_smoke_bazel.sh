#!/usr/bin/env bash
# Smoke test using Bazel (< 5 minutes).
# Runs a fast subset of tests to verify basic correctness.
#
# Usage:
#   bash scripts/testing/verify/smoke/run_smoke_bazel.sh [--skip-build]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"

SKIP_BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1; shift ;;
    *) shift ;;
  esac
done

cd "${DS_ROOT}"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "Building smoke targets with Bazel..."
  bazel build //tests/... 2>&1 | tail -5
fi

echo "Running smoke tests..."
bazel test //tests/... \
  --test_tag_filters=smoke \
  --test_output=errors \
  --jobs="${JOBS:-$(nproc)}" 2>&1 | tail -30

echo "Smoke test done"
