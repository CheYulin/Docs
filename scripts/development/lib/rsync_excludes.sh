#!/usr/bin/env bash
# Common rsync exclude patterns for syncing datasystem and agent-workbench repos.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/rsync_excludes.sh"
#
# Provides:
#   RSYNC_EXCLUDE_ARGS    - array of --exclude arguments
#   rsync_exclude_file()  - function to return exclude file path

set -euo pipefail

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing rsync_excludes.sh}"

# Core exclude patterns shared by all sync operations.
# This array can be passed directly to rsync:
#   rsync -az "${RSYNC_EXCLUDE_ARGS[@]}" src/ dest/
RSYNC_EXCLUDE_ARGS=(
  --exclude '.git/'
  --exclude 'build/'
  --exclude 'build_cov/'
  --exclude '.cache/'
  --exclude 'bazel-*'
  --exclude 'MODULE.bazel.lock'
  --exclude 'third_party/.cache/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude 'CMakeCache.txt'
  --exclude 'CMakeFiles/'
  --exclude 'Testing/'
  --exclude 'compile_commands.json'
)

# Return the path to the canonical rsync ignore file for sync scripts.
rsync_exclude_file() {
  echo "${SCRIPT_DIR}/../development/sync/sync_to_xqyun.rsyncignore"
}

# Return rsync options including exclude-from if available.
rsync_base_opts() {
  local exclude_file
  exclude_file="$(rsync_exclude_file)"
  if [[ -f "$exclude_file" ]]; then
    echo "-az --exclude-from=${exclude_file}"
  else
    echo "-az ${RSYNC_EXCLUDE_ARGS[*]}"
  fi
}
