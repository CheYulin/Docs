#!/usr/bin/env bash
# Resolve yuanrong-datasystem repository root when tooling lives under
# vibe-coding-files/scripts (staging) or inside the datasystem clone.
#
# Prerequisites: caller sets SCRIPT_DIR to the directory containing the invoking
# script (e.g. .../scripts/verify or legacy .../scripts), before sourcing this file.
#
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck source=../lib/datasystem_root.sh
#   . "${SCRIPT_DIR}/../lib/datasystem_root.sh"
#
# Sets: ROOT_DIR  (yuanrong-datasystem checkout)
#
# Override: export DATASYSTEM_ROOT=/path/to/yuanrong-datasystem

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing lib/datasystem_root.sh}"

# Resolve .../scripts (category scripts live in scripts/{build,index,perf,verify}/).
if [[ -f "${SCRIPT_DIR}/lib/datasystem_root.sh" ]]; then
  SCRIPTS_ROOT="${SCRIPT_DIR}"
else
  SCRIPTS_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
_parent="$(cd "${SCRIPTS_ROOT}/.." && pwd)"

if [[ -n "${DATASYSTEM_ROOT:-}" ]]; then
  ROOT_DIR="$(cd "${DATASYSTEM_ROOT}" && pwd)"
elif [[ -f "${_parent}/CMakeLists.txt" ]] && [[ -d "${_parent}/src/datasystem" ]]; then
  ROOT_DIR="${_parent}"
elif [[ -f "${_parent}/../yuanrong-datasystem/CMakeLists.txt" ]]; then
  ROOT_DIR="$(cd "${_parent}/../yuanrong-datasystem" && pwd)"
else
  ROOT_DIR="${_parent}"
fi

unset _parent SCRIPTS_ROOT
