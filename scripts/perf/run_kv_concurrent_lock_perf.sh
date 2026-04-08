#!/usr/bin/env bash
# High-concurrency KV MCreate/MSet/MGet/Exist batch bench (ST cluster). Compare PERF_CONCURRENT_BATCH across builds/commits.
#
# Usage:
#   bash scripts/perf/run_kv_concurrent_lock_perf.sh [build-dir]
# Env (optional):
#   DS_KV_CONC_PERF_THREADS   default 16
#   DS_KV_CONC_PERF_OPS       default 20  (batch rounds per thread, after warmup)
#   DS_KV_CONC_PERF_WARMUP    default 3   (per thread)
#   DS_KV_CONC_BATCH_KEYS     default 4   (keys per MCreate/MSet/MGet/Exist), clamped 1..16
#   DS_KV_CONC_BUF_BYTES      default 4096 (per-key buffer size), clamped 256..524288
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
if [[ $# -ge 1 ]]; then
  BUILD="$1"
else
  BUILD="build"
fi
if [[ "${BUILD}" != /* ]]; then
  BUILD="${ROOT_DIR}/${BUILD}"
fi
BIN="${BUILD}/tests/st/ds_st_kv_cache"
if [[ ! -x "$BIN" ]]; then
  echo "Missing executable: $BIN (build target ds_st_kv_cache first)" >&2
  exit 1
fi

export DS_KV_CONC_PERF_THREADS="${DS_KV_CONC_PERF_THREADS:-16}"
export DS_KV_CONC_PERF_OPS="${DS_KV_CONC_PERF_OPS:-20}"
export DS_KV_CONC_PERF_WARMUP="${DS_KV_CONC_PERF_WARMUP:-3}"
export DS_KV_CONC_BATCH_KEYS="${DS_KV_CONC_BATCH_KEYS:-4}"
export DS_KV_CONC_BUF_BYTES="${DS_KV_CONC_BUF_BYTES:-4096}"

echo "Running KVClientExecutorRuntimeE2ETest.PerfConcurrentMCreateMSetMGetExistUnderContention"
echo "  DS_KV_CONC_PERF_THREADS=$DS_KV_CONC_PERF_THREADS"
echo "  DS_KV_CONC_PERF_OPS=$DS_KV_CONC_PERF_OPS"
echo "  DS_KV_CONC_PERF_WARMUP=$DS_KV_CONC_PERF_WARMUP"
echo "  DS_KV_CONC_BATCH_KEYS=$DS_KV_CONC_BATCH_KEYS"
echo "  DS_KV_CONC_BUF_BYTES=$DS_KV_CONC_BUF_BYTES"
echo

if ctest --test-dir "$BUILD" --output-on-failure -R "PerfConcurrentMCreateMSetMGetExistUnderContention" 2>&1; then
  echo
  echo "Look for a line starting with: PERF_CONCURRENT_BATCH"
  echo "Compare mcreate_/mset_/mget_/exist_ *p95_us / *p99_us before vs after lock-scope changes."
else
  exit 1
fi
