#!/usr/bin/env bash
# Load node configuration from nodes.yaml.
# Provides functions to query per-node SSH host, workspace root, cache path, etc.
#
# Usage (in any script):
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/load_nodes.sh"
#
# Functions:
#   node_default              - print default node name
#   node_ssh_host <name>      - print SSH host for node
#   node_ssh_user <name>       - print SSH user for node
#   node_workspace_root <name> - print workspace root path for node
#   node_hermes_workspace_root <name> - print hermes workspace root for node
#   node_thirdparty_cache <name> - print third-party cache path for node
#   node_pkg_manager <name>    - print package manager (dnf/apt) for node
#
# Environment override:
#   NODE_NAME=<name>           - override default node (useful for hermes agent)

set -euo pipefail

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing load_nodes.sh}"

_load_yaml_path() {
  local dir="${SCRIPT_DIR}"
  # caller is in scripts/lib/ → ../config/ is scripts/config/
  echo "$(cd "${dir}/../config" && pwd)/nodes.yaml"
}

_nodes_parse() {
  if [[ -n "${_NODES_CACHE:-}" ]]; then return; fi

  local yaml_path="$(_load_yaml_path)"
  if [[ ! -f "$yaml_path" ]]; then
    echo "load_nodes.sh: nodes.yaml not found at $yaml_path" >&2
    exit 1
  fi

  # Parse YAML via python3; key=value format, __NODE__ marks new node
  # Uses absolute path so cwd doesn't matter
  _NODES_CACHE="$(python3 -c "
import yaml, sys

with open('${yaml_path}', 'r') as f:
    data = yaml.safe_load(f)

default_node = data.get('default', '')
print('__DEFAULT__|' + default_node)

for node_name, cfg in data.get('nodes', {}).items():
    print('__NODE__|' + node_name)
    print('ssh_host|' + str(cfg.get('ssh_host', '')))
    print('ssh_user|' + str(cfg.get('ssh_user', '')))
    print('workspace_root|' + str(cfg.get('workspace_root', '')))
    print('hermes_workspace_root|' + str(cfg.get('hermes_workspace_root', '')))
    print('thirdparty_cache|' + str(cfg.get('thirdparty_cache', '')))
    print('pkg_manager|' + str(cfg.get('pkg_manager', '')))
" 2>&1)"
}

_nodes_find_node() {
  local node="${1:?_nodes_find_node requires node name}"
  _nodes_parse
  local in_node=0
  local found=0
  while IFS='|' read -r key val; do
    [[ -z "$key" ]] && continue
    if [[ "$key" == "__NODE__" ]]; then
      if [[ "$val" == "$node" ]]; then
        in_node=1
        found=1
      else
        in_node=0
      fi
    elif [[ "$key" != "__DEFAULT__" && "$in_node" -eq 1 ]]; then
      echo "${key}|${val}"
    fi
  done <<< "${_NODES_CACHE}"
  [[ "$found" -eq 1 ]]
}

node_default() {
  _nodes_parse
  echo "${_NODES_CACHE}" | grep '^__DEFAULT__|' | cut -d'|' -f2
}

node_ssh_host() {
  local node="${1:?node_ssh_host: node name required}"
  _nodes_find_node "$node" | grep '^ssh_host|' | cut -d'|' -f2
}

node_ssh_user() {
  local node="${1:?node_ssh_user: node name required}"
  _nodes_find_node "$node" | grep '^ssh_user|' | cut -d'|' -f2
}

node_workspace_root() {
  local node="${1:?node_workspace_root: node name required}"
  _nodes_find_node "$node" | grep '^workspace_root|' | cut -d'|' -f2
}

node_hermes_workspace_root() {
  local node="${1:?node_hermes_workspace_root: node name required}"
  _nodes_find_node "$node" | grep '^hermes_workspace_root|' | cut -d'|' -f2
}

node_thirdparty_cache() {
  local node="${1:?node_thirdparty_cache: node name required}"
  _nodes_find_node "$node" | grep '^thirdparty_cache|' | cut -d'|' -f2
}

node_pkg_manager() {
  local node="${1:?node_pkg_manager: node name required}"
  _nodes_find_node "$node" | grep '^pkg_manager|' | cut -d'|' -f2
}
