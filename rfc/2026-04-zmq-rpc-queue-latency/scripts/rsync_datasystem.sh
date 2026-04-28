#!/usr/bin/env bash
# Rsync local yuanrong-datasystem to remote /root/workspace/git-repos/
# Usage: ./rsync_datasystem.sh
set -euo pipefail

LOCAL_DS="/home/t14s/workspace/git-repos/yuanrong-datasystem"
REMOTE="root@xqyun-32c32g"
REMOTE_DS="/root/workspace/git-repos/yuanrong-datasystem"
RSYNCIGNORE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../scripts/build" && pwd)"
RSYNCIGNORE_FILE="${RSYNCIGNORE_DIR}/remote_build_run_datasystem.rsyncignore"

if [[ ! -d "${LOCAL_DS}/src" ]]; then
  echo "Local DS not found: ${LOCAL_DS}" >&2
  exit 1
fi
if [[ ! -f "${RSYNCIGNORE_FILE}" ]]; then
  echo "rsyncignore not found: ${RSYNCIGNORE_FILE}" >&2
  exit 1
fi

echo "LOCAL_DS=${LOCAL_DS}"
echo "REMOTE=${REMOTE}"
echo "REMOTE_DS=${REMOTE_DS}"
echo

ssh "${REMOTE}" "mkdir -p \"${REMOTE_DS}\""
rsync -az --delete \
  --exclude-from="${RSYNCIGNORE_FILE}" \
  "${LOCAL_DS}/" \
  "${REMOTE}:${REMOTE_DS}/"

echo "Done."
