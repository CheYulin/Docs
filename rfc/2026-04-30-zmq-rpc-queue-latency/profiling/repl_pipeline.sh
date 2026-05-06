#!/usr/bin/env bash
# One-shot: rsync → remote bazel build → remote bazel test (gtest) → local parse_repl_log.py
# Uses the same repl_remote_common.inc.sh as sibling scripts (cache path + BAZEL_JOBS).
#
# Usage:
#   ./repl_pipeline.sh [options] [duration_seconds]
# Options:
#   --skip-sync    Skip rsync (remote tree unchanged)
#   --skip-build   Skip bazel build (use last build)
#   --skip-run     Stop after build
#   --skip-parse   Do not run parse_repl_log.py after run
#   --tee          Forward to bazel_run.sh (live ssh stream; default is remote file + scp)
#   --kv-metrics-ut After remote bazel_build, run //tests/ut/common/metrics:metrics_test
#                  (--test_filter=MetricsTest.kv_metric_urma_id_layout_test) — catches stale
#                  KvMetricId / KV_METRIC_DESCS skew when queue-flow enums shift before URMA worker tail.
# Environment: same as repl_remote_common.inc.sh (REMOTE_*, DS_OPENSOURCE_DIR_REMOTE, BAZEL_JOBS, …)
#
# Examples:
#   ./repl_pipeline.sh
#   BAZEL_JOBS=16 ./repl_pipeline.sh --skip-sync 15
#   ./repl_pipeline.sh --kv-metrics-ut --skip-sync 5   # KV enum/desc sanity before long REPL UT
set -euo pipefail

PROFILING_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/ holds the ST-run helpers; profiling/ holds the profiling scripts
SCRIPTS_DIR="$(cd "${PROFILING_DIR}/../scripts" && pwd)"
# shellcheck source=repl_remote_common.inc.sh
source "${PROFILING_DIR}/repl_remote_common.inc.sh"

SKIP_SYNC=0
SKIP_BUILD=0
SKIP_RUN=0
SKIP_PARSE=0
RUN_TEE=0
KV_METRICS_UT=0
DURATION="5"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-sync) SKIP_SYNC=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    --skip-run) SKIP_RUN=1 ;;
    --skip-parse) SKIP_PARSE=1 ;;
    --tee) RUN_TEE=1 ;;
    --kv-metrics-ut) KV_METRICS_UT=1 ;;
    -h|--help)
      sed -n '1,22p' "$0"
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        DURATION="$1"
      else
        echo "Extra arg: $1" >&2
        exit 1
      fi
      ;;
  esac
  shift
done

echo "=== repl_pipeline: REMOTE=${REMOTE} REMOTE_DS=${REMOTE_DS} DS_OP=${DS_OPENSOURCE_DIR_REMOTE} jobs=${BAZEL_JOBS} duration=${DURATION}s ==="

if [[ "${SKIP_SYNC}" -eq 0 ]]; then
  bash "${SCRIPTS_DIR}/rsync_datasystem.sh"
else
  echo "=== skipping rsync (--skip-sync) ==="
fi

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  bash "${SCRIPTS_DIR}/bazel_build.sh"
else
  echo "=== skipping bazel build (--skip-build) ==="
fi

if [[ "${KV_METRICS_UT}" -eq 1 ]]; then
  echo "=== remote KV metrics URMA-tail layout UT (after build, before repl bazel_run) ==="
  bash "${SCRIPTS_DIR}/bazel_run_kv_metric_urma_layout_ut.sh"
fi

if [[ "${SKIP_RUN}" -eq 0 ]]; then
  if [[ "${RUN_TEE}" -eq 1 ]]; then
    bash "${SCRIPTS_DIR}/bazel_run.sh" --tee "${DURATION}"
  else
    bash "${SCRIPTS_DIR}/bazel_run.sh" "${DURATION}"
  fi
else
  echo "=== skipping bazel run (--skip-run) ==="
fi

LOGFILE="${LOCAL_RESULTS_DIR}/${REPL_LOG_NAME}"
if [[ "${SKIP_PARSE}" -eq 0 ]] && [[ -f "${LOGFILE}" ]]; then
  echo
  echo "=== parse_repl_log.py ==="
  python3 "${SCRIPTS_DIR}/parse_repl_log.py" "${LOGFILE}"
else
  if [[ "${SKIP_PARSE}" -ne 0 ]]; then
    echo "=== skipping parse (--skip-parse) ==="
  elif [[ ! -f "${LOGFILE}" ]]; then
    echo "WARN: no log at ${LOGFILE}, skip parse" >&2
  fi
fi

echo "repl_pipeline done."
