#!/usr/bin/env bash
# Shared env for ZMQ REPL remote workflow (rsync / bazel build / run / parse).
# Source from sibling scripts only:
#   source "${SCRIPT_DIR}/repl_remote_common.inc.sh"
#
# Override via environment when your layout differs:
#   YUANRONG_DATASYSTEM_ROOT  Local clone (default: sibling of agent-workbench)
#   REMOTE_HOST               SSH hostname (default: xqyun-32c32g)
#   REMOTE_USER               SSH user (default: root)
#   REMOTE_DS                 Remote yuanrong-datasystem path
#   DS_OPENSOURCE_DIR_REMOTE  Persistent third_party cache on remote (Bazel toolchain)
#   REMOTE_REPL_LOG_PATH      Remote plain file written by default bazel_run (then scp)
#   BAZEL_JOBS                Parallel jobs for bazel build/run

REPL_REMOTE_COMMON_INC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_WORKBENCH_ROOT="$(cd "${REPL_REMOTE_COMMON_INC_DIR}/../../.." && pwd)"
RFC_ROOT="$(cd "${REPL_REMOTE_COMMON_INC_DIR}/.." && pwd)"

REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_HOST="${REMOTE_HOST:-xqyun-32c32g}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"

REMOTE_REPO_BASE="${REMOTE_REPO_BASE:-/root/workspace/git-repos}"
REMOTE_DS="${REMOTE_DS:-${REMOTE_REPO_BASE}/yuanrong-datasystem}"
DS_OPENSOURCE_DIR_REMOTE="${DS_OPENSOURCE_DIR_REMOTE:-/root/.cache/yuanrong-datasystem-third-party}"
BAZEL_JOBS="${BAZEL_JOBS:-32}"

if [[ -n "${YUANRONG_DATASYSTEM_ROOT:-}" ]]; then
  LOCAL_DS="$(cd "${YUANRONG_DATASYSTEM_ROOT}" && pwd)"
else
  _sibling="$(cd "${AGENT_WORKBENCH_ROOT}/../yuanrong-datasystem" 2>/dev/null && pwd || true)"
  if [[ -n "${_sibling}" ]] && [[ -d "${_sibling}/src" ]]; then
    LOCAL_DS="${_sibling}"
  else
    LOCAL_DS="$(cd "${HOME}/workspace/git-repos/yuanrong-datasystem" && pwd)"
  fi
fi
unset _sibling

RSYNCIGNORE_FILE="${AGENT_WORKBENCH_ROOT}/scripts/build/remote_build_run_datasystem.rsyncignore"
LOCAL_RESULTS_DIR="${LOCAL_RESULTS_DIR:-${RFC_ROOT}/results}"

REPL_BAZEL_TARGET="//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl"
REPL_LOG_NAME="zmq_rpc_queue_latency_repl.log"
# Remote capture file for bazel_run default mode (then scp to LOCAL_RESULTS_DIR).
REMOTE_REPL_LOG_PATH="${REMOTE_REPL_LOG_PATH:-/tmp/zmq_rpc_queue_latency_repl_capture.log}"
