#!/usr/bin/env bash
# =============================================================================
# run_kv_rw_metrics_remote_capture.sh
#
# KV 读写 ST + metrics 日志采集（对齐 run_zmq_rpc_metrics_remote.sh 的远端流程）。
#
# 1) rsync local yuanrong-datasystem → remote（可 SKIP_RSYNC=1）
# 2) 构建：BUILD_BACKEND=bazel（默认）或 cmake
# 3) 跑 ST：默认 KVClientMSetPerfTest.MsetNtxSmallObj；stdout/stderr → 本机
#    vibe-coding-files/results/kv_rw_metrics_<UTC>/ds_st_full.log
# 4) 本地 grep + summarize；可选 FETCH_CHILD_LOGS 拉 worker*/client 日志
#
# 环境变量（均可覆盖）：
#   BUILD_BACKEND     bazel | cmake   （默认 bazel）
#   REMOTE_HOST       默认 xqyun-32c32g
#   REMOTE_DS         默认 /root/workspace/git-repos/yuanrong-datasystem
#   REMOTE_BUILD      默认 ${REMOTE_DS}/build（仅 cmake）
#   LOCAL_DS          默认 <workspace>/yuanrong-datasystem（与 run_zmq 一致）
#   BUILD_JOBS        默认 8
#   SKIP_RSYNC=1      不同步，仅远端构建+跑 ST
#   SKIP_SSH=1        只打印远端脚本，不 rsync / 不 ssh
#   GTEST_FILTER      默认 KVClientMSetPerfTest.MsetNtxSmallObj
#   DS_ST_BIN         仅 cmake：默认 ds_st_kv_cache，路径 REMOTE_BUILD/tests/st/
#   BAZEL_ST_KV       仅 bazel：默认 //tests/st/client/kv_cache:kv_client_mset_test
#   BAZEL_CMD         默认 bazel（可 bazelisk）
#   LOG_MONITOR_MS    默认 8000（仅作用于 ds_st 进程 argv；worker 默认 interval 见 07 文档）
#   FETCH_CHILD_LOGS  默认 1
#
# Bazel 注意：tests/st/cluster 里 WORKER_BIN_PATH 编译为 /usr/local/bin/datasystem_worker
#（见 yuanrong-datasystem/tests/st/cluster/BUILD.bazel）。远端需有可执行 worker，或与 cmake
# 产物一致地安装到该路径后再跑 bazel ST。
#
# mock OBS：getcwd() + "/../../../tests/st/cluster/mock_obs_service.py" —— cwd 须为
# REMOTE_DS 下恰好三层子目录；脚本在远端 mkdir+cd REMOTE_DS/.st_metrics_wr/a/b 再 exec。
# =============================================================================
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-xqyun-32c32g}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
REMOTE_BUILD="${REMOTE_BUILD:-${REMOTE_DS}/build}"
BUILD_JOBS="${BUILD_JOBS:-8}"
BUILD_BACKEND="${BUILD_BACKEND:-bazel}"
SKIP_RSYNC="${SKIP_RSYNC:-0}"
GTEST_FILTER="${GTEST_FILTER:-KVClientMSetPerfTest.MsetNtxSmallObj}"
DS_ST_BIN="${DS_ST_BIN:-ds_st_kv_cache}"
BAZEL_ST_KV="${BAZEL_ST_KV:-//tests/st/client/kv_cache:kv_client_mset_test}"
BAZEL_CMD="${BAZEL_CMD:-bazel}"
LOG_MONITOR_MS="${LOG_MONITOR_MS:-8000}"
SKIP_SSH="${SKIP_SSH:-0}"
FETCH_CHILD_LOGS="${FETCH_CHILD_LOGS:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIBE_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RESULTS_PARENT="${VIBE_ROOT}/results"
LOCAL_DS="${LOCAL_DS:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd || true)}"
SUMMARIZE_SH="${SCRIPT_DIR}/summarize_observability_log.sh"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
OUT_DIR="${RESULTS_PARENT}/kv_rw_metrics_${STAMP}"
mkdir -p "$OUT_DIR"
META="$OUT_DIR/META.txt"

{
  echo "timestamp_utc=$STAMP"
  echo "remote_host=$REMOTE_HOST"
  echo "remote_ds=$REMOTE_DS"
  echo "remote_build=$REMOTE_BUILD"
  echo "build_backend=$BUILD_BACKEND"
  echo "gtest_filter=$GTEST_FILTER"
  echo "cmake_ds_st_binary=$DS_ST_BIN"
  echo "bazel_st_kv=$BAZEL_ST_KV"
  echo "log_monitor_interval_ms=$LOG_MONITOR_MS"
} | tee "$META"

if [[ ! -d "$LOCAL_DS" && "$SKIP_RSYNC" != "1" ]]; then
  echo "ERROR: LOCAL_DS not found: $LOCAL_DS" | tee -a "$META"
  exit 2
fi

REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
set -euo pipefail
bazel_st_kv_bin() {
  local label="$1"
  local bb="$2"
  local pkg="${label#//}"
  local path="${pkg%%:*}"
  local name="${pkg#*:}"
  echo "${bb}/${path}/${name}"
}

if [[ "${BUILD_BACKEND}" == "cmake" ]]; then
  ST_BIN="${REMOTE_BUILD}/tests/st/${DS_ST_BIN}"
  if [[ ! -x "${ST_BIN}" ]]; then
    echo "ERROR: missing ${ST_BIN}" >&2
    echo "Hint: cmake --build ${REMOTE_BUILD} --target ${DS_ST_BIN} -j${BUILD_JOBS}" >&2
    exit 2
  fi
else
  cd "${REMOTE_DS}"
  echo "=== ${BAZEL_CMD} build ${BAZEL_ST_KV} (jobs=${BUILD_JOBS}) ==="
  "${BAZEL_CMD}" build "${BAZEL_ST_KV}" --jobs="${BUILD_JOBS}"
  BB="$("${BAZEL_CMD}" info bazel-bin)"
  ST_BIN="$(bazel_st_kv_bin "${BAZEL_ST_KV}" "${BB}")"
  if [[ ! -x "${ST_BIN}" ]]; then
    echo "ERROR: missing ${ST_BIN} after bazel build" >&2
    exit 2
  fi
fi

mkdir -p "${REMOTE_DS}/.st_metrics_wr/a/b"
cd "${REMOTE_DS}/.st_metrics_wr/a/b"
exec "${ST_BIN}" \
  --gtest_filter="${GTEST_FILTER}" \
  --alsologtostderr \
  -log_monitor=true \
  -log_monitor_interval_ms="${LOG_MONITOR_MS}" \
  2>&1
REMOTE_EOF
)

echo "=== Remote script (build+run) ===" | tee -a "$META"
echo "$REMOTE_SCRIPT" | tee -a "$META"

if [[ "$SKIP_SSH" == "1" ]]; then
  echo "SKIP_SSH=1 — done."
  exit 0
fi

if [[ "$SKIP_RSYNC" != "1" ]]; then
  echo "=== rsync ${LOCAL_DS}/ → ${REMOTE_HOST}:${REMOTE_DS}/ ===" | tee -a "$META"
  rsync -az --delete \
    --exclude '.git/' \
    --exclude 'build/' \
    --exclude '.cache/' \
    --exclude 'bazel-*' \
    --exclude 'MODULE.bazel.lock' \
    "${LOCAL_DS}/" "${REMOTE_HOST}:${REMOTE_DS}/"
else
  echo "SKIP_RSYNC=1 — using existing remote tree" | tee -a "$META"
fi

FULL_LOG="$OUT_DIR/ds_st_full.log"
echo "=== ssh → $FULL_LOG (keepalive) ===" | tee -a "$META"
set +e
ssh -o BatchMode=yes -o ConnectTimeout=30 \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=480 \
  -o TCPKeepAlive=yes \
  "$REMOTE_HOST" \
  env \
    REMOTE_DS="$REMOTE_DS" \
    REMOTE_BUILD="$REMOTE_BUILD" \
    BUILD_BACKEND="$BUILD_BACKEND" \
    BUILD_JOBS="$BUILD_JOBS" \
    DS_ST_BIN="$DS_ST_BIN" \
    BAZEL_ST_KV="$BAZEL_ST_KV" \
    BAZEL_CMD="$BAZEL_CMD" \
    GTEST_FILTER="$GTEST_FILTER" \
    LOG_MONITOR_MS="$LOG_MONITOR_MS" \
  bash -s <<<"$REMOTE_SCRIPT" >"$FULL_LOG" 2>&1
RC=$?
set -e
echo "remote_ssh_exit=$RC" | tee -a "$META"
echo "remote_ssh_exit=$RC" >>"$META"

grep -E '^Metrics Summary|^Total:|^Compare with' "$FULL_LOG" >"$OUT_DIR/grep_metrics_summary.txt" 2>/dev/null || true
grep -E 'client_(put|get|rpc)|worker_(process|rpc|urma|tcp|to_|from_|object|allocated)|zmq_' "$FULL_LOG" \
  >"$OUT_DIR/grep_kv_zmq_metrics_lines.txt" 2>/dev/null || true

if [[ -x "$SUMMARIZE_SH" ]]; then
  bash "$SUMMARIZE_SH" "$FULL_LOG" >"$OUT_DIR/summary.txt" 2>/dev/null || true
fi

if [[ "$FETCH_CHILD_LOGS" == "1" ]]; then
  ROOT_RAW="$(grep -m1 'rootDir:' "$FULL_LOG" 2>/dev/null | sed 's/.*rootDir://' | tr -d '\r' | awk '{print $1}')" || true
  if [[ -n "${ROOT_RAW:-}" ]]; then
    echo "parsed_rootDir=$ROOT_RAW" | tee -a "$META"
    ROOT_Q="$(printf '%q' "$ROOT_RAW")"
    set +e
    CANON="$(ssh -o BatchMode=yes -o ConnectTimeout=30 "$REMOTE_HOST" "readlink -f $ROOT_Q" 2>/dev/null | tr -d '\r')"
    set -e
    [[ -z "$CANON" ]] && CANON="$ROOT_RAW"
    echo "canonical_rootDir=$CANON" | tee -a "$META"
    CLUSTER_DIR="$OUT_DIR/cluster_logs"
    mkdir -p "$CLUSTER_DIR"
    set +e
    ssh -o BatchMode=yes -o ConnectTimeout=30 "$REMOTE_HOST" \
      "cd $(printf '%q' "$CANON") && tar chf - worker0/log worker1/log worker2/log client 2>/dev/null" \
      | tar xf - -C "$CLUSTER_DIR" 2>/dev/null
    FT=$?
    set -e
    echo "fetch_child_logs_tar_exit=$FT" | tee -a "$META"
    if [[ -d "$CLUSTER_DIR/worker0/log" ]]; then
      grep -rhE '^Metrics Summary|^Total:|^Compare with' "$CLUSTER_DIR" >"$OUT_DIR/grep_metrics_summary_children.txt" 2>/dev/null || true
      grep -rhE 'client_(put|get|rpc)|worker_(process|rpc|urma|tcp|to_|from_|object|allocated)|zmq_' "$CLUSTER_DIR" \
        >"$OUT_DIR/grep_kv_zmq_metrics_lines_children.txt" 2>/dev/null || true
    fi
  else
    echo "parsed_rootDir=(empty, skip child log fetch)" | tee -a "$META"
  fi
fi

echo "OUT_DIR=$OUT_DIR"
exit "$RC"
