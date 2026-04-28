#!/usr/bin/env bash
# 默认在远端 Bazel 构建：先 rsync 本地 yuanrong-datasystem，再 ssh 执行 bazel。
# 说明与构建产物排查见同目录 REMOTE_BAZEL_BUILD.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKBENCH_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RSYNC_IGNORE_FILE="${SCRIPT_DIR}/remote_build_run_datasystem.rsyncignore"
DS_DIR_NAME="yuanrong-datasystem"

REMOTE="${REMOTE:-xqyun-32c32g}"
REMOTE_BASE="${REMOTE_BASE:-"\${HOME}/workspace/git-repos"}"
BAZEL_CMD="${BAZEL_CMD:-bazel}"
# 限制 Bazel 并发 action 数，避免占满 CPU/IO；未设置时默认 16。
: "${BAZEL_JOBS:=16}"
SKIP_SYNC=0
INSPECT_ONLY=0
REMOTE_DS=""

if [[ -n "${DATASYSTEM_ROOT:-}" ]]; then
  LOCAL_DS="$(cd "${DATASYSTEM_ROOT}" && pwd)"
else
  _sibling="${WORKBENCH_ROOT}/../${DS_DIR_NAME}"
  if [[ -d "${_sibling}/src" ]]; then
    LOCAL_DS="$(cd "${_sibling}" && pwd)"
  else
    echo "Set DATASYSTEM_ROOT, or clone yuanrong-datasystem at: ${_sibling}" >&2
    exit 1
  fi
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote) REMOTE="$2"; shift 2 ;;
    --local-ds) LOCAL_DS="$(cd "$2" && pwd)"; shift 2 ;;
    --remote-ds) REMOTE_DS="$2"; shift 2 ;;
    --skip-sync) SKIP_SYNC=1; shift ;;
    --inspect-only) INSPECT_ONLY=1; shift ;;
    -h|--help)
      echo "Usage: $0 [options] -- <bazel subcommand and targets...>" >&2
      echo "  $0 -- build //path/to:target" >&2
      echo "  $0 --inspect-only   # 只打印远端 bazel release / bazel-bin / output_path" >&2
      echo "  $0 --skip-sync -- test //...   # 不 rsync，只跑 bazel" >&2
      echo "Env: REMOTE, DATASYSTEM_ROOT, BAZEL_CMD, BAZEL_JOBS (default 16)" >&2
      echo "Doc: ${SCRIPT_DIR}/REMOTE_BAZEL_BUILD.md" >&2
      exit 0
      ;;
    --) shift; break ;;
    *) echo "Unknown: $1 (put bazel args after a single --)" >&2; exit 2 ;;
  esac
done
# 允许误写两次 --：bazel 不需要前导 --
while [[ $# -gt 0 && "$1" == "--" ]]; do
  shift
done

if [[ ! -f "${RSYNC_IGNORE_FILE}" ]]; then
  echo "Missing: ${RSYNC_IGNORE_FILE}" >&2
  exit 1
fi

REMOTE_HOME="$(ssh "${REMOTE}" 'printf %s "$HOME"')"
if [[ -z "${REMOTE_DS}" ]]; then
  _b="${REMOTE_BASE//\$\{HOME\}/$REMOTE_HOME}"
  _b="${_b//\$HOME/$REMOTE_HOME}"
  _b="${_b//\~/$REMOTE_HOME}"
  REMOTE_DS="${_b}/${DS_DIR_NAME}"
fi
DS_OPENSOURCE_DIR_REMOTE="${REMOTE_HOME}/.cache/yuanrong-datasystem-third-party"

echo "LOCAL_DS=${LOCAL_DS}"
echo "REMOTE=${REMOTE}  REMOTE_DS=${REMOTE_DS}"
echo "BAZEL_JOBS=${BAZEL_JOBS} (Bazel --jobs)"
echo

if [[ "${SKIP_SYNC}" -eq 0 ]]; then
  echo "[rsync] -> ${REMOTE}:${REMOTE_DS}/"
  ssh "${REMOTE}" "mkdir -p \"${REMOTE_DS}\""
  rsync -az --delete --exclude-from="${RSYNC_IGNORE_FILE}" "${LOCAL_DS}/" "${REMOTE}:${REMOTE_DS}/"
else
  echo "[rsync] skipped (--skip-sync)"
fi

quoted=""
if [[ $# -gt 0 ]]; then
  for _a; do
    quoted+=" $(printf '%q' "${_a}")"
  done
  quoted="${quoted# }"
fi

if [[ "${INSPECT_ONLY}" -eq 1 ]]; then
  # shellcheck disable=SC2029
  ssh "${REMOTE}" "
    set -euo pipefail
    export DS_OPENSOURCE_DIR='${DS_OPENSOURCE_DIR_REMOTE}'
    mkdir -p \"\${DS_OPENSOURCE_DIR}\"
    cd '${REMOTE_DS}'
    ${BAZEL_CMD} info release 2>/dev/null || true
    ${BAZEL_CMD} info bazel-bin
    ${BAZEL_CMD} info output_path
  "
  echo "见 REMOTE_BAZEL_BUILD.md §4（构建产物）"
  exit 0
fi

if [[ -z "${quoted}" ]]; then
  quoted="build //..."
  echo "No bazel args; default: build //..."
fi

# shellcheck disable=SC2029
ssh "${REMOTE}" "
  set -euo pipefail
  export DS_OPENSOURCE_DIR='${DS_OPENSOURCE_DIR_REMOTE}'
  mkdir -p \"\${DS_OPENSOURCE_DIR}\"
  cd '${REMOTE_DS}'
  ${BAZEL_CMD} info release 2>/dev/null || true
  ${BAZEL_CMD} info bazel-bin
  ${BAZEL_CMD} info output_path
  ${BAZEL_CMD} --jobs=\"${BAZEL_JOBS}\" ${quoted}
"
echo
echo "产物与排查: ${SCRIPT_DIR}/REMOTE_BAZEL_BUILD.md"
