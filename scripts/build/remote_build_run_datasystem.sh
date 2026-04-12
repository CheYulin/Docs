#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
# shellcheck source=../lib/vibe_coding_root.sh
. "${SCRIPT_DIR}/../lib/vibe_coding_root.sh"

LOCAL_DS="${ROOT_DIR}"
LOCAL_VIBE="${VIBE_CODING_ROOT}"
REMOTE="rsync@yuanrong-datasystem"
REMOTE_BASE="~/workspace/git-repos"
REMOTE_DS=""
REMOTE_VIBE=""
BUILD_DIR_REL="build"
DS_OPENSOURCE_DIR="~/.cache/yuanrong-datasystem-third-party"
RSYNC_IGNORE_FILE="${SCRIPT_DIR}/remote_build_run_datasystem.rsyncignore"
SKIP_SYNC=0
INSTALL_DEPS=0
BUILD_JOBS="${JOBS:-}"
CTEST_JOBS="${CTEST_JOBS:-}"
SKIP_CTEST=0
SKIP_VALIDATE=0
SKIP_RUN_EXAMPLE=0
SKIP_WHEEL_INSTALL=0

usage() {
  cat <<'EOF'
Usage:
  bash scripts/build/remote_build_run_datasystem.sh [options]

Default behavior:
  1) rsync local yuanrong-datasystem + vibe-coding-files to remote host
  2) run remote build (build.sh -t build -B <DS>/build)
  3) run ctest
  4) run vibe validate_kv_executor.sh --skip-build
  5) run build.sh -t run_example
  6) install built wheel to user site-packages (best effort)

Options:
  --remote <user@host>            Remote SSH target (default: rsync@yuanrong-datasystem)
  --remote-base <path>            Remote workspace base (default: ~/workspace/git-repos)
  --remote-ds <path>              Remote DS absolute path (default: <remote-base>/yuanrong-datasystem)
  --remote-vibe <path>            Remote vibe absolute path (default: <remote-base>/vibe-coding-files)
  --local-ds <path>               Local yuanrong-datasystem path (default: resolved by lib/datasystem_root.sh)
  --local-vibe <path>             Local vibe-coding-files path (default: current repo root)
  --build-dir-rel <path>          Build directory relative to remote DS root (default: build)
  --opensource-cache <path>       DS_OPENSOURCE_DIR on remote (default: $HOME/.cache/yuanrong-datasystem-third-party)
  --rsync-ignore-file <path>      rsync exclude file for sync phase
  --jobs <N>                      Build parallel jobs (default: remote nproc)
  --ctest-jobs <N>                ctest parallel jobs (default: same as --jobs)
  --skip-sync                     Skip rsync and only execute remote build/test/run steps
  --install-deps                  Try to install C++/CMake/Python deps on remote (dnf or apt-get)
  --skip-ctest                    Skip ctest --test-dir
  --skip-validate                 Skip validate_kv_executor.sh
  --skip-run-example              Skip build.sh -t run_example
  --skip-wheel-install            Skip wheel install + dscli --version check
  -h, --help                      Show this help

Environment:
  JOBS                            Same as --jobs
  CTEST_JOBS                      Same as --ctest-jobs
EOF
}

abspath() {
  local p="$1"
  if [[ -d "$p" ]]; then
    (cd "$p" && pwd)
  else
    echo "Path does not exist: $p" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE="$2"
      shift 2
      ;;
    --remote-base)
      REMOTE_BASE="$2"
      shift 2
      ;;
    --remote-ds)
      REMOTE_DS="$2"
      shift 2
      ;;
    --remote-vibe)
      REMOTE_VIBE="$2"
      shift 2
      ;;
    --local-ds)
      LOCAL_DS="$(abspath "$2")"
      shift 2
      ;;
    --local-vibe)
      LOCAL_VIBE="$(abspath "$2")"
      shift 2
      ;;
    --build-dir-rel)
      BUILD_DIR_REL="$2"
      shift 2
      ;;
    --opensource-cache)
      DS_OPENSOURCE_DIR="$2"
      shift 2
      ;;
    --rsync-ignore-file)
      RSYNC_IGNORE_FILE="$2"
      shift 2
      ;;
    --jobs)
      BUILD_JOBS="$2"
      shift 2
      ;;
    --ctest-jobs)
      CTEST_JOBS="$2"
      shift 2
      ;;
    --skip-sync)
      SKIP_SYNC=1
      shift
      ;;
    --install-deps)
      INSTALL_DEPS=1
      shift
      ;;
    --skip-ctest)
      SKIP_CTEST=1
      shift
      ;;
    --skip-validate)
      SKIP_VALIDATE=1
      shift
      ;;
    --skip-run-example)
      SKIP_RUN_EXAMPLE=1
      shift
      ;;
    --skip-wheel-install)
      SKIP_WHEEL_INSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

LOCAL_DS="$(abspath "${LOCAL_DS}")"
LOCAL_VIBE="$(abspath "${LOCAL_VIBE}")"
RSYNC_IGNORE_FILE="$(abspath "$(dirname "${RSYNC_IGNORE_FILE}")")/$(basename "${RSYNC_IGNORE_FILE}")"
if [[ ! -f "${RSYNC_IGNORE_FILE}" ]]; then
  echo "Missing rsync ignore file: ${RSYNC_IGNORE_FILE}" >&2
  exit 1
fi

if [[ -z "${REMOTE_DS}" ]]; then
  REMOTE_DS="${REMOTE_BASE%/}/yuanrong-datasystem"
fi
if [[ -z "${REMOTE_VIBE}" ]]; then
  REMOTE_VIBE="${REMOTE_BASE%/}/vibe-coding-files"
fi

REMOTE_HOME="$(ssh "${REMOTE}" 'printf %s "$HOME"')"
resolve_remote_path() {
  local p="$1"
  p="${p/#\~\//${REMOTE_HOME}/}"
  p="${p/#\~/${REMOTE_HOME}}"
  p="${p/#\$HOME\//${REMOTE_HOME}/}"
  p="${p/#\$HOME/${REMOTE_HOME}}"
  printf '%s' "${p}"
}
REMOTE_DS_RESOLVED="$(resolve_remote_path "${REMOTE_DS}")"
REMOTE_VIBE_RESOLVED="$(resolve_remote_path "${REMOTE_VIBE}")"
REMOTE_OPENSOURCE_DIR_RESOLVED="$(resolve_remote_path "${DS_OPENSOURCE_DIR}")"

echo "== local =="
echo "LOCAL_DS=${LOCAL_DS}"
echo "LOCAL_VIBE=${LOCAL_VIBE}"
echo
echo "== remote =="
echo "REMOTE=${REMOTE}"
echo "REMOTE_DS=${REMOTE_DS_RESOLVED}"
echo "REMOTE_VIBE=${REMOTE_VIBE_RESOLVED}"
echo "BUILD_DIR_REL=${BUILD_DIR_REL}"
echo "RSYNC_IGNORE_FILE=${RSYNC_IGNORE_FILE}"
echo "DS_OPENSOURCE_DIR=${REMOTE_OPENSOURCE_DIR_RESOLVED}"
echo "BUILD_JOBS=${BUILD_JOBS:-auto}"
echo "CTEST_JOBS=${CTEST_JOBS:-auto}"
echo

if [[ "${SKIP_SYNC}" -eq 0 ]]; then
  echo "[sync 1/3] Create remote workspace directories"
  ssh "${REMOTE}" "mkdir -p \"${REMOTE_DS_RESOLVED}\" \"${REMOTE_VIBE_RESOLVED}\""

  RSYNC_COMMON_OPTS=(
    -az
    --delete
    --exclude-from="${RSYNC_IGNORE_FILE}"
  )

  echo "[sync 2/3] Sync yuanrong-datasystem -> ${REMOTE}:${REMOTE_DS_RESOLVED}"
  rsync "${RSYNC_COMMON_OPTS[@]}" "${LOCAL_DS}/" "${REMOTE}:${REMOTE_DS_RESOLVED}/"

  echo "[sync 3/3] Sync vibe-coding-files -> ${REMOTE}:${REMOTE_VIBE_RESOLVED}"
  rsync "${RSYNC_COMMON_OPTS[@]}" "${LOCAL_VIBE}/" "${REMOTE}:${REMOTE_VIBE_RESOLVED}/"
else
  echo "[sync] Skipped (--skip-sync)"
fi

REMOTE_BUILD_DIR="${REMOTE_DS_RESOLVED%/}/${BUILD_DIR_REL}"

echo "[remote] Run build/test/example workflow"
ssh "${REMOTE}" \
  "REMOTE_DS='${REMOTE_DS_RESOLVED}' REMOTE_VIBE='${REMOTE_VIBE_RESOLVED}' REMOTE_BUILD_DIR='${REMOTE_BUILD_DIR}' DS_OPENSOURCE_DIR='${REMOTE_OPENSOURCE_DIR_RESOLVED}' INSTALL_DEPS='${INSTALL_DEPS}' SKIP_CTEST='${SKIP_CTEST}' SKIP_VALIDATE='${SKIP_VALIDATE}' SKIP_RUN_EXAMPLE='${SKIP_RUN_EXAMPLE}' SKIP_WHEEL_INSTALL='${SKIP_WHEEL_INSTALL}' BUILD_JOBS='${BUILD_JOBS}' CTEST_JOBS='${CTEST_JOBS}' bash -s" <<'EOF'
set -euo pipefail

echo "== preflight =="
python3 --version || true
uname -s || true
uname -m || true
ldd --version | head -n 1 || true

if [[ "${INSTALL_DEPS}" == "1" ]]; then
  echo "[deps] Installing build dependencies on remote host..."
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y \
      gcc gcc-c++ make cmake pkgconf-pkg-config \
      python3 python3-pip python3-devel \
      git wget curl tar which openssl-devel zlib-devel libstdc++-devel \
      patch autoconf automake libtool perl-FindBin
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y \
      build-essential cmake ninja-build pkg-config \
      python3 python3-pip python3-dev \
      git wget curl tar \
      libssl-dev zlib1g-dev \
      patch autoconf automake libtool perl
  else
    echo "No supported package manager found (dnf/apt-get)." >&2
    exit 1
  fi
fi

export DS="${REMOTE_DS}"
export VIBE="${REMOTE_VIBE}"
export DATASYSTEM_ROOT="${DS}"
export DS_OPENSOURCE_DIR
mkdir -p "${DS_OPENSOURCE_DIR}"

if [[ -z "${BUILD_JOBS}" ]]; then
  BUILD_JOBS="$(nproc)"
fi
if [[ -z "${CTEST_JOBS}" ]]; then
  CTEST_JOBS="${BUILD_JOBS}"
fi
echo "Parallel jobs: build=${BUILD_JOBS}, ctest=${CTEST_JOBS}"

echo
echo "== build =="
cd "${DS}"
export JOBS="${BUILD_JOBS}"
bash build.sh -t build -B "${REMOTE_BUILD_DIR}"

if [[ "${SKIP_CTEST}" != "1" ]]; then
  echo
  echo "== ctest =="
  export CTEST_OUTPUT_ON_FAILURE=1
  ctest --test-dir "${REMOTE_BUILD_DIR}" --output-on-failure --parallel "${CTEST_JOBS}"
else
  echo "[ctest] Skipped (--skip-ctest)"
fi

if [[ "${SKIP_VALIDATE}" != "1" ]]; then
  echo
  echo "== validate_kv_executor =="
  bash "${VIBE}/scripts/verify/validate_kv_executor.sh" --skip-build "${REMOTE_BUILD_DIR}"
else
  echo "[validate] Skipped (--skip-validate)"
fi

if [[ "${SKIP_RUN_EXAMPLE}" != "1" ]]; then
  echo
  echo "== run_example =="
  bash build.sh -t run_example
else
  echo "[run_example] Skipped (--skip-run-example)"
fi

if [[ "${SKIP_WHEEL_INSTALL}" != "1" ]]; then
  echo
  echo "== wheel install =="
  WHEEL_PATH="$(find "${DS}/output" "${DS}/build" -maxdepth 6 -name 'openyuanrong_datasystem-*.whl' 2>/dev/null | head -n 1 || true)"
  if [[ -n "${WHEEL_PATH}" ]]; then
    python3 -m pip install --user "${WHEEL_PATH}"
    if command -v dscli >/dev/null 2>&1; then
      dscli --version
    else
      echo "dscli not in PATH yet (usually in ~/.local/bin)."
    fi
  else
    echo "No wheel found under ${DS}/output or ${DS}/build; skip install."
  fi
else
  echo "[wheel] Skipped (--skip-wheel-install)"
fi

echo
echo "Remote build workflow finished."
EOF
