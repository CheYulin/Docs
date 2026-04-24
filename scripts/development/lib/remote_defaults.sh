#!/usr/bin/env bash
# Remote execution defaults: SSH host, rsync, path resolution.
# Depends on: load_nodes.sh, common.sh
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/load_nodes.sh"
#   . "${SCRIPT_DIR}/common.sh"
#   . "${SCRIPT_DIR}/remote_defaults.sh"
#
# Sets:
#   REMOTE        - SSH target (user@host)
#   REMOTE_BASE   - Remote workspace root
#   DS_OPENSOURCE_DIR - Remote third-party cache path

set -euo pipefail

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing remote_defaults.sh}"

# Source dependencies
. "${SCRIPT_DIR}/load_nodes.sh"
. "${SCRIPT_DIR}/common.sh"

# Determine node name: NODE_NAME env var overrides default
_remote_node_name() {
  echo "${NODE_NAME:-$(node_default)}"
}

# Resolve tilde and $HOME in remote paths using the remote shell.
# Usage: resolve_remote_path <path_with_tilde_or_$HOME>
resolve_remote_path() {
  local path="$1"
  local remote="${REMOTE:?REMOTE must be set before calling resolve_remote_path}"
  local remote_home
  remote_home="$(ssh "$remote" 'printf %s "$HOME"' 2>/dev/null)" || remote_home="$HOME"
  # Replace ~ and $HOME with actual remote home
  local resolved="${path/#\~\//${remote_home}/}"
  resolved="${resolved/#\~/${remote_home}}"
  resolved="${resolved/#\$HOME\//${remote_home}/}"
  resolved="${resolved/#\$HOME/${remote_home}}"
  printf '%s' "$resolved"
}

# Initialize remote configuration from node name.
# Call this once at the start of a remote script:
#   init_remote <node_name>
init_remote() {
  local node="${1:?init_remote: node name required}"
  local ssh_user ssh_host

  ssh_user="$(node_ssh_user "$node")"
  ssh_host="$(node_ssh_host "$node")"
  REMOTE="${ssh_user}@${ssh_host}"

  local ws_root
  ws_root="$(node_workspace_root "$node")"
  REMOTE_BASE="$(resolve_remote_path "$ws_root")"

  local cache_path
  cache_path="$(node_thirdparty_cache "$node")"
  DS_OPENSOURCE_DIR="$(resolve_remote_path "$cache_path")"

  log_info "Remote: ${REMOTE}"
  log_info "Remote base: ${REMOTE_BASE}"
  log_info "Third-party cache: ${DS_OPENSOURCE_DIR}"
}

# SSH with batch mode and keepalive options.
# Usage: ssh_remote <args...>
ssh_remote() {
  ssh -o BatchMode=yes \
      -o ConnectTimeout=30 \
      -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=480 \
      -o TCPKeepAlive=yes \
      "$@"
}

# SSH with minimal options (for quick checks).
ssh_remote_quick() {
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$@"
}

# Create remote directories if they do not exist.
# Usage: ensure_remote_dirs <dir1> [<dir2>...]
ensure_remote_dirs() {
  local remote="${REMOTE:?ensure_remote_dirs: REMOTE not set}"
  local dirs=("$@")
  local dir_list
  printf -v dir_list '%s ' "${dirs[@]}"
  ssh_remote "$remote" "mkdir -p ${dir_list}"
}
