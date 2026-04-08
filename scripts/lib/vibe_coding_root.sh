#!/usr/bin/env bash
# Resolve vibe-coding-files repository root (parent of scripts/).
# Use for artifact paths under workspace/ (bpftrace, perf, strace reports).
#
# Prerequisites: SCRIPT_DIR set to the invoking script's directory (same as datasystem_root.sh).
#
# Sets: VIBE_CODING_ROOT

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing lib/vibe_coding_root.sh}"

if [[ -f "${SCRIPT_DIR}/lib/datasystem_root.sh" ]]; then
  SCRIPTS_ROOT="${SCRIPT_DIR}"
else
  SCRIPTS_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
VIBE_CODING_ROOT="$(cd "${SCRIPTS_ROOT}/.." && pwd)"
unset SCRIPTS_ROOT
