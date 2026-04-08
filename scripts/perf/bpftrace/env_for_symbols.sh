#!/usr/bin/env bash
# Source before running bpftrace (same shell as sudo -E):
#   source scripts/perf/bpftrace/env_for_symbols.sh
#   sudo -E bpftrace ...
#
# Or: sudo env LLVM_SYMBOLIZER_PATH=... BPFTRACE_... bpftrace ...

# Prefer a recent llvm-symbolizer (bpftrace uses it for C++ demangling / symbols).
if [[ -z "${LLVM_SYMBOLIZER_PATH:-}" ]]; then
    for cand in llvm-symbolizer-18 llvm-symbolizer-17 llvm-symbolizer-16 llvm-symbolizer; do
        if command -v "$cand" &>/dev/null; then
            LLVM_SYMBOLIZER_PATH="$(command -v "$cand")"
            export LLVM_SYMBOLIZER_PATH
            break
        fi
    done
fi

# Longer strings in maps / comm (bpftrace default can truncate).
# Keep default within older bpftrace hard limit (often 200).
export BPFTRACE_MAX_STRLEN="${BPFTRACE_MAX_STRLEN:-200}"

# Larger aggregation maps if needed (optional).
export BPFTRACE_MAX_MAP_KEYS="${BPFTRACE_MAX_MAP_KEYS:-200000}"
# Cache user symbols to improve ustack symbol resolution for shared libs.
export BPFTRACE_CACHE_USER_SYMBOLS="${BPFTRACE_CACHE_USER_SYMBOLS:-1}"

echo "[env_for_symbols] LLVM_SYMBOLIZER_PATH=${LLVM_SYMBOLIZER_PATH:-<not found — install llvm-symbolizer>}"
echo "[env_for_symbols] BPFTRACE_MAX_STRLEN=$BPFTRACE_MAX_STRLEN"
echo "[env_for_symbols] BPFTRACE_CACHE_USER_SYMBOLS=$BPFTRACE_CACHE_USER_SYMBOLS"
