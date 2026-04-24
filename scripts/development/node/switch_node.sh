#!/usr/bin/env bash
# Switch the default node in nodes.yaml.
#
# Usage:
#   bash scripts/development/node/switch_node.sh <node_name>
#
# Example:
#   bash scripts/development/node/switch_node.sh centos9-new

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YAML_PATH="${SCRIPT_DIR}/../../config/nodes.yaml"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/development/node/switch_node.sh <node_name>

Example:
  bash scripts/development/node/switch_node.sh centos9-new
EOF
}

NEW_NODE="${1:-}"
if [[ -z "${NEW_NODE}" ]]; then
  echo "node name required" >&2
  usage >&2
  exit 1
fi

if [[ ! -f "${YAML_PATH}" ]]; then
  echo "nodes.yaml not found at ${YAML_PATH}" >&2
  exit 1
fi

# Verify node exists
if ! python3 -c "
import yaml
with open('${YAML_PATH}') as f:
    data = yaml.safe_load(f)
nodes = data.get('nodes', {})
if '${NEW_NODE}' not in nodes:
    print(f\"Node '${NEW_NODE}' not found. Available: {', '.join(nodes.keys())}\")
    exit(1)
" 2>&1; then
  exit 1
fi

# Update default in YAML
python3 -c "
import yaml
with open('${YAML_PATH}') as f:
    data = yaml.safe_load(f)
data['default'] = '${NEW_NODE}'
with open('${YAML_PATH}') as f:
    yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
print('Switched default node to: ${NEW_NODE}')
"

echo "Current default:"
python3 -c "
import yaml
with open('${YAML_PATH}') as f:
    data = yaml.safe_load(f)
print('  default:', data.get('default', '(none)'))
print('  nodes:', ', '.join(data.get('nodes', {}).keys()))
"
