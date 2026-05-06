#!/usr/bin/env bash
# Bazel build zmq_rpc_queue_latency_repl on remote (same cache + jobs as sibling scripts).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=repl_remote_common.inc.sh
source "${SCRIPT_DIR}/repl_remote_common.inc.sh"

echo "REMOTE=${REMOTE}"
echo "REMOTE_DS=${REMOTE_DS}"
echo "DS_OPENSOURCE_DIR=${DS_OPENSOURCE_DIR_REMOTE}"
echo "BAZEL_JOBS=${BAZEL_JOBS}"
echo

ssh "${REMOTE}" bash -s "${REMOTE_DS}" "${DS_OPENSOURCE_DIR_REMOTE}" "${BAZEL_JOBS}" "${REPL_BAZEL_TARGET}" <<'REMOTESCRIPT'
set -euo pipefail
REMOTE_DS="$1"
DS_OP="$2"
JOBS="$3"
TARGET="$4"
export DS_OPENSOURCE_DIR="${DS_OP}"
mkdir -p "${DS_OPENSOURCE_DIR}"
cd "${REMOTE_DS}"
bazel info release 2>/dev/null || true
echo "=== Building ${TARGET} (jobs=${JOBS}) ==="
bazel build "${TARGET}" --config=perf --config=release --jobs="${JOBS}"
REMOTESCRIPT

echo "Build done."
