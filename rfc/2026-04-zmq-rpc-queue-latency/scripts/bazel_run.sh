#!/usr/bin/env bash
# Bazel run zmq_rpc_queue_latency_test and/or zmq_rpc_queue_latency_repl on remote
# Usage:
#   ./bazel_run.sh              # run both
#   ./bazel_run.sh repl 5       # run repl only, 5 seconds
#   ./bazel_run.sh test         # run test only
set -euo pipefail

REMOTE="root@xqyun-32c32g"
REMOTE_DS="/root/workspace/git-repos/yuanrong-datasystem"
DS_OPENSOURCE_DIR_REMOTE="/root/.cache/yuanrong-datasystem-third-party"
LOCAL_RESULTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../results" && pwd)"

mkdir -p "${LOCAL_RESULTS_DIR}"

TARGET="${1:-}"
DURATION_ARG="${2:-}"

echo "REMOTE=${REMOTE}"
echo "REMOTE_DS=${REMOTE_DS}"
echo "DS_OPENSOURCE_DIR=${DS_OPENSOURCE_DIR_REMOTE}"
echo "TARGET=${TARGET}"
echo "DURATION_ARG=${DURATION_ARG}"
echo "LOCAL_RESULTS_DIR=${LOCAL_RESULTS_DIR}"
echo

do_run() {
    local bazel_target="$1"
    local logname="$2"
    local extra_args="${3:-}"
    local logfile="${LOCAL_RESULTS_DIR}/${logname}.log"

    echo "=== Running ${bazel_target} ==="
    echo "=== Log: ${logfile} ==="

    local remote_cmd="cd /root/workspace/git-repos/yuanrong-datasystem && bazel run ${bazel_target} -- --logtostderr=1 ${extra_args}"

    ssh "${REMOTE}" "${remote_cmd}" 2>&1 | tee "${logfile}"
    echo
}

case "${TARGET}" in
    repl)
        args=""
        [[ -n "${DURATION_ARG}" ]] && args="--duration=${DURATION_ARG}"
        do_run '//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl' 'zmq_rpc_queue_latency_repl' "${args}"
        ;;
    test)
        do_run '//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_test' 'zmq_rpc_queue_latency_test' ""
        ;;
    "")
        # Run both: repl first (with optional duration), then test
        args=""
        [[ -n "${DURATION_ARG}" ]] && args="--duration=${DURATION_ARG}"
        do_run '//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl' 'zmq_rpc_queue_latency_repl' "${args}"
        do_run '//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_test' 'zmq_rpc_queue_latency_test' ""
        ;;
    *)
        echo "Unknown target: ${TARGET}" >&2
        echo "Usage: $0 [repl|test] [duration_seconds]" >&2
        exit 1
        ;;
esac

echo "Run done. Logs in ${LOCAL_RESULTS_DIR}/"
ls -lh "${LOCAL_RESULTS_DIR}/"
