#!/usr/bin/env bash
# Timing utilities for measuring and reporting step durations.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/timing.sh"
#
# Provides:
#   run_timed <step_name> <cmd> [args...]
#   print_timing_report
#   banner <message>   - print a timestamped section header

set -euo pipefail

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing timing.sh}"

TIMING_REPORT=""

# Print a section header with timestamp.
banner() {
  printf '\n========== [%s] %s ==========\n' "$(date -u '+%H:%M:%S')" "$*"
}

# Run a command and record its elapsed time.
# Usage: run_timed <step_name> <cmd> [args...]
# Sets $step_elapsed on return (in seconds).
run_timed() {
  local step="$1"
  shift
  local started ended elapsed
  started="$(date +%s)"
  if "$@"; then
    ended="$(date +%s)"
    elapsed=$((ended - started))
    log_info "[done] ${step} (${elapsed}s)"
    TIMING_REPORT+="${step}|${elapsed}|OK"$'\n'
    return 0
  else
    ended="$(date +%s)"
    elapsed=$((ended - started))
    log_error "[fail] ${step} (${elapsed}s)"
    TIMING_REPORT+="${step}|${elapsed}|FAIL"$'\n'
    return 1
  fi
}

# Print a summary of all timed steps.
print_timing_report() {
  if [[ -z "${TIMING_REPORT}" ]]; then return; fi
  echo
  echo "== timing summary =="
  printf '%-44s %-10s %-6s\n' "STEP" "ELAPSED" "STATUS"
  while IFS='|' read -r step elapsed status; do
    [[ -z "${step}" ]] && continue
    printf '%-44s %-10ss %-6s\n' "${step}" "${elapsed}" "${status}"
  done <<< "${TIMING_REPORT}"
}

# Short timestamp for log prefixes.
ts() {
  date -u '+%H:%M:%S'
}
