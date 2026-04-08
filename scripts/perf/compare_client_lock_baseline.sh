#!/usr/bin/env bash
# Compare two collect_client_lock_baseline.sh output directories (no sudo).
# Usage:
#   bash scripts/perf/compare_client_lock_baseline.sh RUN_DIR_A RUN_DIR_B
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/perf/compare_client_lock_baseline.sh <run_dir_a> <run_dir_b>

Example:
  bash scripts/perf/compare_client_lock_baseline.sh \
    plans/client_lock_baseline/runs/20260403_220000_abc1234 \
    plans/client_lock_baseline/runs/20260404_090000_def5678

Prints: unified diff of RUN_META.txt, gate_exit.code, perf_exit.code, SUMMARY.txt
EOF
}

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 1
fi

A="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
B="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"

for d in "$A" "$B"; do
  if [[ ! -d "$d" ]]; then
    echo "Not a directory: $d" >&2
    exit 1
  fi
done

echo "=== RUN_META.txt ==="
diff -u "${A}/RUN_META.txt" "${B}/RUN_META.txt" || true

echo ""
echo "=== gate_exit.code / perf_exit.code ==="
printf '%s\n' "A=${A}" "B=${B}"
cat "${A}/gate_exit.code" 2>/dev/null | sed 's/^/A gate_exit: /' || echo "A gate_exit: (missing)"
cat "${B}/gate_exit.code" 2>/dev/null | sed 's/^/B gate_exit: /' || echo "B gate_exit: (missing)"
cat "${A}/perf_exit.code" 2>/dev/null | sed 's/^/A perf_exit: /' || echo "A perf_exit: (missing)"
cat "${B}/perf_exit.code" 2>/dev/null | sed 's/^/B perf_exit: /' || echo "B perf_exit: (missing)"

echo ""
if [[ -f "${A}/perf/kv_executor_perf_summary.txt" && -f "${B}/perf/kv_executor_perf_summary.txt" ]]; then
  echo "=== perf absolute latency us_mean (A vs B, for acceptance) ==="
  echo "--- A ---"
  grep -E '^(inline|injected)_(set|get)_avg_us_mean=' "${A}/perf/kv_executor_perf_summary.txt" || true
  echo "--- B ---"
  grep -E '^(inline|injected)_(set|get)_avg_us_mean=' "${B}/perf/kv_executor_perf_summary.txt" || true
  echo ""
fi

echo "=== SUMMARY.txt ==="
diff -u "${A}/SUMMARY.txt" "${B}/SUMMARY.txt" || true

echo ""
echo "[TIP] Full logs: diff -u ${A}/gate_validate.log ${B}/gate_validate.log | less"
