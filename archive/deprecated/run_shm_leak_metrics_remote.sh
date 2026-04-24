#!/usr/bin/env bash
# =============================================================================
# run_shm_leak_metrics_remote.sh
#
# 一站式 build+test+归档 脚本（基于 RFC 2026-04-shm-leak-observability Phase 1）。
#
# 设计参考：
#   - vibe-coding-files/scripts/build/remote_build_run_datasystem.sh
#       → 用 DS_OPENSOURCE_DIR 缓存第三方库（避免每次 30 min 重新编译）
#   - vibe-coding-files/scripts/testing/verify/run_zmq_metrics_ut_regression_remote.sh
#       → 远端 build+UT 流程
#
# 三个新增能力（你提的）：
#   1) 第三方库专门缓存目录：DS_OPENSOURCE_DIR=~/.cache/yuanrong-datasystem-third-party
#      → build.sh / cmake 会复用这个目录，二次构建只编译我们改的代码（≈1-3 min）
#   2) Build OOM-aware 重试：jobs 减半 ≤3 轮（保险机制，xqyun-32c32g 30GB 一般用不到）
#   3) 进度打印 + 大文件清理（rocksdb/etcd/spdlog 落盘）+ UT 用时记录
#
# 默认 BUILD_BACKEND=cmake；Bazel 路径可用（BUILD_BACKEND=bazel）但需远端有
# 完整的 datasystem_mallctl 链路，详见 build.log。
#
# 关键环境变量（均可覆盖）：
#   REMOTE_HOST          默认 xqyun-32c32g    (32 core / 30 GB)
#   REMOTE_DS            默认 /root/workspace/git-repos/yuanrong-datasystem
#   LOCAL_DS             默认 sibling of this script
#   DS_OPENSOURCE_DIR    默认 ~/.cache/yuanrong-datasystem-third-party（远端路径）
#   BUILD_BACKEND        cmake | bazel        （默认 cmake）
#   BUILD_JOBS           默认 32              （xqyun-32c32g: 32 core / 30 GB；OOM 时自动减半）
#   BUILD_RETRIES        默认 3
#   CMAKE_TARGET         默认 ds_ut           （UT 目标，新 UT 在 ds_ut）
#   CMAKE_BIN            默认 ds_ut           （二进制名）
#   GTEST_FILTER         默认 'ShmLeakMetricsTest.*'
#   BAZEL_UT             仅 BUILD_BACKEND=bazel 时使用
#   BAZEL_EXTRA_OPTS     仅 bazel：额外参数（默认 --config=no_urma_sdk，无 URMA/RDMA 的节点必用）
#   FORCE_FULL_BUILD     1 = 删 build/ 重新 configure（默认 0，增量）
#   SKIP_RSYNC           1 = 跳过同步
#   SKIP_SSH             1 = 仅打印远端脚本
#   PRUNE_LOGS           1 = 归档前清大文件（默认 1）
#
# 大文件 prune 规则：rocksdb sst/MANIFEST、etcd snap.db/wal、worker .log、>50MB 文件
# =============================================================================
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-xqyun-32c32g}"
REMOTE_DS="${REMOTE_DS:-/root/workspace/git-repos/yuanrong-datasystem}"
DS_OPENSOURCE_DIR="${DS_OPENSOURCE_DIR:-/root/.cache/yuanrong-datasystem-third-party}"
BUILD_BACKEND="${BUILD_BACKEND:-cmake}"
BUILD_JOBS="${BUILD_JOBS:-32}"  # xqyun-32c32g: 32 cores, 30 GB RAM — full parallelism is safe
BUILD_RETRIES="${BUILD_RETRIES:-3}"
CMAKE_TARGET="${CMAKE_TARGET:-ds_ut}"
CMAKE_BIN="${CMAKE_BIN:-ds_ut}"
BAZEL_UT="${BAZEL_UT:-//tests/ut/common/metrics:shm_leak_metrics_test}"
# 远端无 UB/URMA/RDMA 时与仓库 .bazelrc 中 no_urma_sdk 一致；本机有 SDK 时可 export BAZEL_EXTRA_OPTS=''
BAZEL_EXTRA_OPTS="${BAZEL_EXTRA_OPTS---config=no_urma_sdk}"
GTEST_FILTER="${GTEST_FILTER:-ShmLeakMetricsTest.*}"
FORCE_FULL_BUILD="${FORCE_FULL_BUILD:-0}"
SKIP_RSYNC="${SKIP_RSYNC:-0}"
SKIP_SSH="${SKIP_SSH:-0}"
PRUNE_LOGS="${PRUNE_LOGS:-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIBE_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
LOCAL_DS="${LOCAL_DS:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd || true)}"
RESULTS_PARENT="${VIBE_ROOT}/results"
RSYNC_IGNORE_FILE="${VIBE_ROOT}/scripts/build/remote_build_run_datasystem.rsyncignore"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
OUT_DIR="${RESULTS_PARENT}/shm_leak_metrics_${STAMP}"
mkdir -p "$OUT_DIR"

META="$OUT_DIR/META.txt"
BUILD_LOG="$OUT_DIR/build.log"
TEST_LOG="$OUT_DIR/test.log"

log() { printf '\n[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" | tee -a "$META"; }

{
  echo "=== run_shm_leak_metrics_remote.sh ==="
  echo "timestamp_utc=$STAMP"
  echo "remote_host=$REMOTE_HOST"
  echo "remote_ds=$REMOTE_DS"
  echo "ds_opensource_dir=$DS_OPENSOURCE_DIR"
  echo "build_backend=$BUILD_BACKEND"
  echo "build_jobs=$BUILD_JOBS"
  echo "build_retries=$BUILD_RETRIES"
  echo "cmake_target=$CMAKE_TARGET"
  echo "cmake_bin=$CMAKE_BIN"
  echo "bazel_ut=$BAZEL_UT"
  echo "bazel_extra_opts=$BAZEL_EXTRA_OPTS"
  echo "gtest_filter=$GTEST_FILTER"
  echo "force_full_build=$FORCE_FULL_BUILD"
} | tee "$META"

if [[ ! -d "$LOCAL_DS" && "$SKIP_RSYNC" != "1" ]]; then
  echo "ERROR: LOCAL_DS not found: $LOCAL_DS" | tee -a "$META"
  exit 2
fi
if [[ ! -f "$RSYNC_IGNORE_FILE" ]]; then
  echo "ERROR: rsync ignore file not found: $RSYNC_IGNORE_FILE" | tee -a "$META"
  exit 2
fi

# -----------------------------------------------------------------------------
# 远端脚本：build (OOM 重试 + 第三方缓存) + run UT (带 timing) + 大文件 prune
# -----------------------------------------------------------------------------
REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
set -uo pipefail   # 不用 -e，让 build 失败时我们能 retry

ts() { date -u +%H:%M:%S; }
banner() { printf '\n========== [%s] %s ==========\n' "$(ts)" "$*"; }

cd "${REMOTE_DS}"

mem_low_kb() { awk '/^MemAvailable:/ {print $2}' /proc/meminfo; }

# Make sure third-party cache dir exists; build.sh respects DS_OPENSOURCE_DIR.
mkdir -p "${DS_OPENSOURCE_DIR}"
export DS_OPENSOURCE_DIR

# If existing CMakeCache points to a different DS_OPENSOURCE_DIR, force fresh
# configure so the new cache dir takes effect (mirrors remote_build_run_datasystem.sh).
if [[ -f "${REMOTE_DS}/build/CMakeCache.txt" ]]; then
  cached="$(sed -n 's/^DS_OPENSOURCE_DIR:PATH=//p' "${REMOTE_DS}/build/CMakeCache.txt" | tail -n 1)"
  if [[ -n "${cached}" && "${cached}" != "${DS_OPENSOURCE_DIR}" ]]; then
    banner "DS_OPENSOURCE_DIR changed (${cached} → ${DS_OPENSOURCE_DIR}); removing CMakeCache"
    rm -f "${REMOTE_DS}/build/CMakeCache.txt"
  fi
fi
if [[ "${FORCE_FULL_BUILD}" == "1" ]]; then
  banner "FORCE_FULL_BUILD=1 → removing ${REMOTE_DS}/build"
  rm -rf "${REMOTE_DS}/build"
fi

build_cmake_full() {
  # build.sh is needed if either:
  #   (a) no build dir exists yet, or
  #   (b) configure didn't finish (no Makefile) — common after a prior fail
  # Otherwise we can incrementally build the target with cmake --build.
  local jobs="$1"
  local need_full=0
  if [[ ! -d "${REMOTE_DS}/build" ]]; then
    need_full=1
  elif [[ ! -f "${REMOTE_DS}/build/CMakeCache.txt" ]]; then
    need_full=1
  elif [[ ! -f "${REMOTE_DS}/build/Makefile" && ! -f "${REMOTE_DS}/build/build.ninja" ]]; then
    need_full=1
  fi
  if (( need_full )); then
    banner "full build.sh -t build (jobs=${jobs}, DS_OPENSOURCE_DIR=${DS_OPENSOURCE_DIR}, incremental=on)"
    JOBS="${jobs}" bash build.sh -t build -B "${REMOTE_DS}/build" -i on -j "${jobs}" -M off
    return $?
  fi
  banner "incremental cmake --build target=${CMAKE_TARGET} (jobs=${jobs})"
  ( cd "${REMOTE_DS}/build" && cmake --build . --target "${CMAKE_TARGET}" -j"${jobs}" )
  return $?
}

cleanup_thirdparty_failed_markers() {
  # build_thirdparty.sh writes ${MULTI_BUILD}/dependency/<lib>.failed on first failure
  # and uses it as a short-circuit. We must wipe these between retries or stale failures
  # poison the next attempt (e.g. openssl.failed → libcurl/grpc never even start).
  local dep_dir="${REMOTE_DS}/build/multi_build/dependency"
  if [[ -d "${dep_dir}" ]]; then
    local removed
    removed=$(find "${dep_dir}" -name '*.failed' -print -delete 2>/dev/null | wc -l)
    if (( removed > 0 )); then
      banner "cleaned ${removed} stale .failed markers from multi_build/dependency/"
    fi
  fi
}

build_with_retry() {
  local jobs="$1"
  local rc=99
  local attempt=0
  while (( attempt < BUILD_RETRIES )); do
    attempt=$((attempt + 1))
    banner "build attempt ${attempt}/${BUILD_RETRIES} (jobs=${jobs}, MemAvailable=$(mem_low_kb)kB)"
    if [[ "${BUILD_BACKEND}" == "cmake" ]]; then
      cleanup_thirdparty_failed_markers
      build_cmake_full "${jobs}"
      rc=$?
    else
      # shellcheck disable=SC2086
      USE_BAZEL_VERSION=7.6.2 bazel build ${BAZEL_EXTRA_OPTS} "${BAZEL_UT}" \
        --jobs="${jobs}" --show_progress_rate_limit=2 --color=no
      rc=$?
    fi
    if (( rc == 0 )); then
      banner "build SUCCESS in attempt ${attempt}"
      return 0
    fi
    if (( jobs > 1 )); then
      jobs=$(( jobs / 2 ))
      banner "build FAIL rc=${rc}; halving jobs to ${jobs} and retrying"
    else
      banner "build FAIL rc=${rc} at jobs=1; not retrying"
      return ${rc}
    fi
  done
  return ${rc}
}

run_test() {
  banner "run UT (filter=${GTEST_FILTER})"
  if [[ "${BUILD_BACKEND}" == "cmake" ]]; then
    local bin="${REMOTE_DS}/build/tests/ut/${CMAKE_BIN}"
    if [[ ! -x "${bin}" ]]; then
      echo "[error] missing UT binary: ${bin}" >&2
      return 2
    fi
    "${bin}" --gtest_filter="${GTEST_FILTER}" --gtest_print_time=1 --alsologtostderr
  else
    # shellcheck disable=SC2086
    USE_BAZEL_VERSION=7.6.2 bazel test ${BAZEL_EXTRA_OPTS} "${BAZEL_UT}" \
      --jobs="${BUILD_JOBS}" --color=no \
      --test_output=streamed --test_arg="--gtest_print_time=1"
  fi
}

prune_big() {
  if [[ "${PRUNE_LOGS:-1}" != "1" ]]; then
    return 0
  fi
  banner "prune large files (rocksdb/etcd/spdlog) to keep archive small"
  for d in "${REMOTE_DS}/.st_metrics_wr" /tmp/leak_metrics_run; do
    [[ -d "$d" ]] || continue
    find "$d" -type f \
      \( -name '*.sst' -o -name 'MANIFEST*' -o -name 'OPTIONS-*' \
         -o -name 'snap.db' -o -name '*.wal' -o -name '*.log' \
         -o -size +50M \) \
      -print -delete 2>/dev/null | head -50 || true
  done
}

banner "build phase  (BUILD_BACKEND=${BUILD_BACKEND}, jobs=${BUILD_JOBS})"
build_with_retry "${BUILD_JOBS}"
BRC=$?
if (( BRC != 0 )); then
  banner "BUILD FINAL FAIL rc=${BRC}"
  prune_big
  exit ${BRC}
fi

banner "test phase"
run_test
TRC=$?
banner "test exit=${TRC}"
prune_big
exit ${TRC}
REMOTE_EOF
)

echo "$REMOTE_SCRIPT" >"$OUT_DIR/remote_script.sh"

if [[ "$SKIP_SSH" == "1" ]]; then
  log "SKIP_SSH=1 — only printed remote script, exiting"
  exit 0
fi

# -----------------------------------------------------------------------------
# rsync local → remote (preserve build/, third-party cache, .git)
# -----------------------------------------------------------------------------
if [[ "$SKIP_RSYNC" != "1" ]]; then
  log "rsync ${LOCAL_DS}/ → ${REMOTE_HOST}:${REMOTE_DS}/  (excludes from ${RSYNC_IGNORE_FILE})"
  rsync -az --delete \
    --exclude-from="${RSYNC_IGNORE_FILE}" \
    "${LOCAL_DS}/" "${REMOTE_HOST}:${REMOTE_DS}/"
else
  log "SKIP_RSYNC=1 — using existing remote tree"
fi

# -----------------------------------------------------------------------------
# ssh execute remote script with all env propagated (single-quoted to prevent
# zsh glob expansion of '*' in GTEST_FILTER etc.)
# -----------------------------------------------------------------------------
ENV_PREAMBLE=$(cat <<EOF
export REMOTE_DS='${REMOTE_DS}'
export DS_OPENSOURCE_DIR='${DS_OPENSOURCE_DIR}'
export BUILD_BACKEND='${BUILD_BACKEND}'
export BUILD_JOBS='${BUILD_JOBS}'
export BUILD_RETRIES='${BUILD_RETRIES}'
export CMAKE_TARGET='${CMAKE_TARGET}'
export CMAKE_BIN='${CMAKE_BIN}'
export BAZEL_UT='${BAZEL_UT}'
export BAZEL_EXTRA_OPTS='${BAZEL_EXTRA_OPTS}'
export GTEST_FILTER='${GTEST_FILTER}'
export FORCE_FULL_BUILD='${FORCE_FULL_BUILD}'
export PRUNE_LOGS='${PRUNE_LOGS}'
EOF
)

log "ssh build+test → ${BUILD_LOG} (keepalive)"
set +e
ssh -o BatchMode=yes -o ConnectTimeout=30 \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=480 \
    -o TCPKeepAlive=yes \
    "$REMOTE_HOST" \
    bash -s <<<"${ENV_PREAMBLE}
${REMOTE_SCRIPT}" >"$BUILD_LOG" 2>&1
RC=$?
set -e

log "remote exit=$RC"
echo "remote_exit=$RC" >>"$META"

# -----------------------------------------------------------------------------
# 提取 test 输出 + UT 用时 + build 用时
# -----------------------------------------------------------------------------
{
  echo "=== test output (last 200 lines) ==="
  tail -200 "$BUILD_LOG"
} >"$TEST_LOG" 2>&1 || true

# Test timing summary (gtest --gtest_print_time=1: "[       OK ] Suite.Case (Xms)")
grep -E '^\[ +(OK|FAILED|RUN) +\]' "$BUILD_LOG" >"$OUT_DIR/gtest_timing.txt" 2>/dev/null || true
grep -E '\[==========\] [0-9]+ tests' "$BUILD_LOG" | tail -3 >"$OUT_DIR/gtest_summary.txt" 2>/dev/null || true
# Build timing
grep -E 'Elapsed time:|build (SUCCESS|FAIL)|test exit=|\[done\] |\[fail\] ' "$BUILD_LOG" >"$OUT_DIR/build_timing.txt" 2>/dev/null || true

log "OUT_DIR=$OUT_DIR"
echo "  - $BUILD_LOG"
echo "  - $TEST_LOG"
echo "  - $OUT_DIR/gtest_timing.txt"
echo "  - $OUT_DIR/gtest_summary.txt"
echo "  - $OUT_DIR/build_timing.txt"

exit "$RC"
