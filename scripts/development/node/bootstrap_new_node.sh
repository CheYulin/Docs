#!/usr/bin/env bash
# Bootstrap a new CentOS 9 node: install deps, sync code, build.
# Target: < 30 minutes on a fresh node.
#
# Usage:
#   bash scripts/development/node/bootstrap_new_node.sh --node <name> [--dry-run]
#
# Requires:
#   - SSH key access to the target node
#   - Local DS_ROOT and VIBE_ROOT set correctly

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DS_ROOT="${DATASYSTEM_ROOT:-$(cd "${SCRIPT_DIR}/../../../../yuanrong-datasystem" 2>/dev/null && pwd)}"
VIBE_ROOT="${SCRIPT_DIR}/../../.."

usage() {
  cat <<'EOF'
Usage:
  bash scripts/development/node/bootstrap_new_node.sh --node <name> [--dry-run]

Options:
  --node <name>     Node name from nodes.yaml (e.g. centos9-new)
  --dry-run         Preview steps without executing
  -h, --help       Show this help

Requires:
  - SSH key access to target node
  - Local yuanrong-datasystem at DATASYSTEM_ROOT or ../yuanrong-datasystem
EOF
}

DRY_RUN=0
NODE_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --node) NODE_NAME="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ -z "${NODE_NAME}" ]]; then
  echo "--node is required" >&2
  usage >&2
  exit 1
fi

echo "== bootstrap plan =="
echo "  node: ${NODE_NAME}"
echo "  DS_ROOT: ${DS_ROOT}"
echo "  VIBE_ROOT: ${VIBE_ROOT}"
echo "  dry-run: ${DRY_RUN}"
echo

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "[dry-run] Would execute bootstrap for ${NODE_NAME}"
  exit 0
fi

# Step 1: SSH connect check
echo "[1/7] SSH connection check..."
ssh -o BatchMode=yes -o ConnectTimeout=10 "${NODE_NAME}" 'echo "SSH OK"' || {
  echo "SSH failed. Ensure key-based auth is configured." >&2; exit 1; }

# Step 2: Detect package manager
echo "[2/7] Detecting package manager..."
PKG_MGR=$(ssh "${NODE_NAME}" 'if command -v dnf >/dev/null 2>&1; then echo dnf; elif command -v apt-get >/dev/null 2>&1; then echo apt-get; else echo unknown; fi')
echo "  package manager: ${PKG_MGR}"

# Step 3: Install build dependencies
echo "[3/7] Installing build dependencies..."
ssh "${NODE_NAME}" bash -c '
  PKG_MGR='"${PKG_MGR}"'
  if [[ "$PKG_MGR" == dnf ]]; then
    sudo dnf install -y gcc gcc-c++ make cmake ninja-build pkgconf-pkg-config \
      python3 python3-pip python3-devel python3-wheel git wget curl tar \
      patch autoconf automake libtool perl net-tools which rsync \
      bazelisk || echo "Some packages may have failed (non-fatal)"
  elif [[ "$PKG_MGR" == apt-get ]]; then
    sudo apt-get update
    sudo apt-get install -y build-essential cmake ninja-build pkg-config \
      python3 python3-pip python3-dev python3-wheel \
      git wget curl tar patch autoconf automake libtool perl net-tools rsync \
      bazelisk || echo "Some packages may have failed (non-fatal)"
  fi
'

# Step 4: Create directory structure
echo "[4/7] Creating directory structure..."
ssh "${NODE_NAME}" bash -c '
  mkdir -p ~/workspace/git-repos ~/agent/hermes-workspace ~/.cache/yuanrong-datasystem-third-party
'

# Step 5: Clone agent-workbench from GitHub (hermes can reach GitHub)
echo "[5/7] Cloning agent-workbench from GitHub..."
ssh "${NODE_NAME}" bash -c '
  if [[ -d ~/workspace/git-repos/yuanrong-datasystem-agent-workbench ]]; then
    echo "agent-workbench already exists, skipping clone"
  else
    git clone https://github.com/<your-org>/yuanrong-datasystem-agent-workbench.git ~/workspace/git-repos/yuanrong-datasystem-agent-workbench
  fi
'

# Step 6: Sync datasystem from local (rsync, hermes cant reach gitcode)
echo "[6/7] Syncing yuanrong-datasystem from local..."
LOCAL_DS="${DS_ROOT}"
REMOTE_DS="root@${NODE_NAME}:~/workspace/git-repos/yuanrong-datasystem"
echo "  rsync ${LOCAL_DS}/ -> ${REMOTE_DS}/"
rsync -az --delete \
  --exclude '.git/' \
  --exclude 'build/' \
  --exclude 'bazel-*' \
  --exclude '.cache/' \
  "${LOCAL_DS}/" "${REMOTE_DS}/"
echo "  sync done"

# Step 7: Build verification
echo "[7/7] Build verification..."
ssh "${NODE_NAME}" bash -c '
  export DS_OPENSOURCE_DIR="$HOME/.cache/yuanrong-datasystem-third-party"
  mkdir -p "$DS_OPENSOURCE_DIR"
  cd ~/workspace/git-repos/yuanrong-datasystem
  bash build.sh -t build -B build -b cmake -j $(nproc) 2>&1 | tail -10
'

echo
echo "== bootstrap complete for ${NODE_NAME} =="
echo "  Connect: ssh root@${NODE_NAME}"
echo "  Workspace: ~/workspace/git-repos/yuanrong-datasystem"
echo "  Build: cd ~/workspace/git-repos/yuanrong-datasystem && bash build.sh -t build"
