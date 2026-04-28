#!/usr/bin/env bash
# Bazel build zmq_rpc_queue_latency_test and zmq_rpc_queue_latency_repl on remote
# Usage: ./bazel_build.sh
set -euo pipefail

REMOTE="root@xqyun-32c32g"
REMOTE_DS="/root/workspace/git-repos/yuanrong-datasystem"
DS_OPENSOURCE_DIR_REMOTE="/root/.cache/yuanrong-datasystem-third-party"
BAZEL_JOBS="${BAZEL_JOBS:-32}"

echo "REMOTE=${REMOTE}"
echo "REMOTE_DS=${REMOTE_DS}"
echo "DS_OPENSOURCE_DIR=${DS_OPENSOURCE_DIR_REMOTE}"
echo "BAZEL_JOBS=${BAZEL_JOBS}"
echo

ssh "${REMOTE}" <<'EOF'
set -euo pipefail
export DS_OPENSOURCE_DIR='/root/.cache/yuanrong-datasystem-third-party'
mkdir -p "${DS_OPENSOURCE_DIR}"

cd '/root/workspace/git-repos/yuanrong-datasystem'

bazel info release 2>/dev/null || true
bazel info bazel-bin
bazel info output_path

echo "=== Building zmq_rpc_queue_latency_test ==="
bazel build '//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_test' --jobs=32

echo "=== Building zmq_rpc_queue_latency_repl ==="
bazel build '//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl' --jobs=32
EOF

echo "Build done."
