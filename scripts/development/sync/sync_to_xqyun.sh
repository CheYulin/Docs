#!/usr/bin/env bash
# Sync local yuanrong-datasystem-agent-workbench/ and yuanrong-datasystem/ to remote host.
#
# 特点：
#   - 保留 .git/ 一起同步（方便在远端 `git status` / `git log`）。
#   - 忽略构建 / 运行产物（见同目录 sync_to_xqyun.rsyncignore）。
#   - 默认使用 rsync -az（不带 --delete）：远端上本地没有的文件会被保留，
#     这样远端的 build/、output/、日志、.cache/ 等构建/运行产物不会被误删。
#   - 需要严格镜像同步时显式加 --delete。
#   - 同时支持只同步其中一个仓库（--skip-vibe / --skip-datasystem）。
#
# 用法：
#   bash scripts/development/sync/sync_to_xqyun.sh                 # 正式同步（保留远端多余文件）
#   bash scripts/development/sync/sync_to_xqyun.sh -n              # dry-run，只预览
#   bash scripts/development/sync/sync_to_xqyun.sh --delete        # 严格镜像，远端多余文件会删
#   bash scripts/development/sync/sync_to_xqyun.sh --skip-vibe     # 只同步 yuanrong-datasystem
#   bash scripts/development/sync/sync_to_xqyun.sh --host other-host --remote-base '~/sandbox'

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 解析 yuanrong-datasystem-agent-workbench / yuanrong-datasystem 根目录。
# 脚本位于 <workbench>/scripts/development/sync/，向上 3 级是 workbench 根。
# yuanrong-datasystem 默认位于 workbench 同级。
WORKBENCH_ROOT="${WORKBENCH_ROOT:-$(cd "${SCRIPT_DIR}/../../.." && pwd)}"
if [[ -n "${DATASYSTEM_ROOT:-}" ]]; then
  ROOT_DIR="$(cd "${DATASYSTEM_ROOT}" && pwd)"
elif [[ -f "${WORKBENCH_ROOT}/../yuanrong-datasystem/CMakeLists.txt" ]]; then
  ROOT_DIR="$(cd "${WORKBENCH_ROOT}/../yuanrong-datasystem" && pwd)"
else
  echo "Cannot locate yuanrong-datasystem checkout. " \
       "Set DATASYSTEM_ROOT=/path/to/yuanrong-datasystem and retry." >&2
  exit 1
fi

REMOTE="xqyun-32c32g"
REMOTE_BASE="~/workspace/git-repos"
RSYNC_IGNORE_FILE="${SCRIPT_DIR}/sync_to_xqyun.rsyncignore"
DRY_RUN=0
DO_DELETE=0
SKIP_DS=0
SKIP_VIBE=0
EXTRA_RSYNC_ARGS=()

usage() {
  cat <<'EOF'
Usage: sync_to_xqyun.sh [options]

Options:
  -n, --dry-run             rsync dry-run（不实际写入远端）
      --delete              严格镜像：远端多余文件会被删（默认关）
      --no-delete           不删除远端多余文件（默认行为，显式声明用）
      --host <name>         远端 SSH Host（默认 xqyun-32c32g）
      --remote-base <path>  远端根目录（默认 ~/workspace/git-repos）
      --ignore-file <path>  自定义 rsync 排除文件（默认 ./sync_to_xqyun.rsyncignore）
      --skip-datasystem     跳过 yuanrong-datasystem 同步
      --skip-vibe           跳过 vibe-coding-files 同步
      --                    其后的参数原样透传给 rsync（高级用法）
  -h, --help                显示本帮助

Examples:
  # 先 dry-run 看看会传哪些文件
  bash scripts/development/sync/sync_to_xqyun.sh -n

  # 正式同步（默认行为）
  bash scripts/development/sync/sync_to_xqyun.sh

  # 只同步 vibe-coding-files
  bash scripts/development/sync/sync_to_xqyun.sh --skip-datasystem
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run)       DRY_RUN=1 ;;
    --no-delete)        DO_DELETE=0 ;;
    --delete)           DO_DELETE=1 ;;
    --host)             REMOTE="$2"; shift ;;
    --remote-base)      REMOTE_BASE="$2"; shift ;;
    --ignore-file)      RSYNC_IGNORE_FILE="$2"; shift ;;
    --skip-datasystem)  SKIP_DS=1 ;;
    --skip-vibe)        SKIP_VIBE=1 ;;
    -h|--help)          usage; exit 0 ;;
    --)                 shift; EXTRA_RSYNC_ARGS+=("$@"); break ;;
    *)  echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ ! -f "${RSYNC_IGNORE_FILE}" ]]; then
  echo "Missing rsync ignore file: ${RSYNC_IGNORE_FILE}" >&2
  exit 1
fi

# 远端目录名与本地顶层目录名保持一致
LOCAL_DS="${ROOT_DIR}"
LOCAL_VIBE="${WORKBENCH_ROOT}"
REMOTE_DS="${REMOTE_BASE%/}/$(basename "${LOCAL_DS}")"
REMOTE_VIBE="${REMOTE_BASE%/}/$(basename "${LOCAL_VIBE}")"

RSYNC_OPTS=(
  -az
  --no-owner
  --no-group
  --chown=root:root
  --human-readable
  --info=stats2,progress2
  --exclude-from="${RSYNC_IGNORE_FILE}"
)
(( DO_DELETE )) && RSYNC_OPTS+=(--delete)
(( DRY_RUN ))   && RSYNC_OPTS+=(--dry-run)
if (( ${#EXTRA_RSYNC_ARGS[@]} )); then
  RSYNC_OPTS+=("${EXTRA_RSYNC_ARGS[@]}")
fi

echo "== sync plan =="
echo "  REMOTE            = ${REMOTE}"
echo "  REMOTE_BASE       = ${REMOTE_BASE}"
echo "  LOCAL_DS          = ${LOCAL_DS}"
echo "  LOCAL_VIBE        = ${LOCAL_VIBE}"
echo "  REMOTE_DS         = ${REMOTE_DS}"
echo "  REMOTE_VIBE       = ${REMOTE_VIBE}"
echo "  IGNORE_FILE       = ${RSYNC_IGNORE_FILE}"
echo "  rsync opts        = ${RSYNC_OPTS[*]}"
echo "  skip datasystem   = ${SKIP_DS}"
echo "  skip vibe         = ${SKIP_VIBE}"
echo

if (( SKIP_DS && SKIP_VIBE )); then
  echo "Both --skip-datasystem and --skip-vibe set; nothing to do." >&2
  exit 0
fi

# 预创建远端目录（dry-run 也创建，空目录无副作用；若需要完全只读可自行去掉）
if (( DRY_RUN == 0 )); then
  ssh "${REMOTE}" "mkdir -p \"${REMOTE_DS}\" \"${REMOTE_VIBE}\""
fi

if (( SKIP_DS == 0 )); then
  echo "[rsync] -> ${REMOTE}:${REMOTE_DS}/"
  rsync "${RSYNC_OPTS[@]}" "${LOCAL_DS}/" "${REMOTE}:${REMOTE_DS}/"
  echo
fi

if (( SKIP_VIBE == 0 )); then
  echo "[rsync] -> ${REMOTE}:${REMOTE_VIBE}/"
  rsync "${RSYNC_OPTS[@]}" "${LOCAL_VIBE}/" "${REMOTE}:${REMOTE_VIBE}/"
  echo
fi

echo "Done."
