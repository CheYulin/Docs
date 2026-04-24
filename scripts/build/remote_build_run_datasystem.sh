#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Source new shared libs
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
. "${SCRIPT_DIR}/../lib/common.sh"
. "${SCRIPT_DIR}/../lib/load_nodes.sh"
. "${SCRIPT_DIR}/../lib/timing.sh"

LOCAL_DS="${ROOT_DIR}"
LOCAL_VIBE="${VIBE_CODING_ROOT}"
REMOTE="xqyun-32c32g"
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
BUILD_HETERO="off"
BUILD_PERF="off"
SKIP_CTEST=0
SKIP_VALIDATE=0
SKIP_RUN_EXAMPLE=0
SKIP_WHEEL_INSTALL=0
BUILD_INCREMENT="on"
VALIDATE_URMA_TCP_LOGS=0
URMA_LOG_PATH=""

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
  --remote <user@host>            Remote SSH target (default: xqyun-32c32g)
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
  --hetero <on|off>               Pass -X to build.sh (default: off)
  --perf <on|off>                 Pass -p to build.sh (default: off)
  --skip-sync                     Skip rsync and only execute remote build/test/run steps
  --install-deps                  Try to install C++/CMake/Python deps on remote (dnf or apt-get)
  --skip-ctest                    Skip ctest --test-dir
  --skip-validate                 Skip validate_kv_executor.sh
  --skip-run-example              Skip build.sh -t run_example
  --skip-wheel-install            Skip wheel install + dscli --version check
  --incremental <on|off>          build.sh incremental mode (default: on)
  --validate-urma-tcp-logs        Run URMA/TCP observability log validator
  --urma-log-path <path>          Remote log file/dir for URMA log validation (optional)
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
    --hetero)
      BUILD_HETERO="$2"
      shift 2
      ;;
    --perf)
      BUILD_PERF="$2"
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
    --incremental)
      BUILD_INCREMENT="$2"
      shift 2
      ;;
    --validate-urma-tcp-logs)
      VALIDATE_URMA_TCP_LOGS=1
      shift
      ;;
    --urma-log-path)
      URMA_LOG_PATH="$2"
      shift 2
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
  REMOTE_VIBE="${REMOTE_BASE%/}/yuanrong-datasystem-agent-workbench"
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
REMOTE_URMA_LOG_PATH_RESOLVED=""
if [[ -n "${URMA_LOG_PATH}" ]]; then
  REMOTE_URMA_LOG_PATH_RESOLVED="$(resolve_remote_path "${URMA_LOG_PATH}")"
fi

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
echo "BUILD_HETERO=${BUILD_HETERO}"
echo "BUILD_PERF=${BUILD_PERF}"
echo "BUILD_INCREMENT=${BUILD_INCREMENT}"
echo "VALIDATE_URMA_TCP_LOGS=${VALIDATE_URMA_TCP_LOGS}"
echo "URMA_LOG_PATH=${REMOTE_URMA_LOG_PATH_RESOLVED:-auto-detect}"
echo

if [[ "${SKIP_SYNC}" -eq 0 ]]; then
  run_timed "sync.prepare_remote_dirs" \
    ssh "${REMOTE}" "mkdir -p \"${REMOTE_DS_RESOLVED}\" \"${REMOTE_VIBE_RESOLVED}\""

  RSYNC_COMMON_OPTS=(
    -az
    --delete
    --exclude-from="${RSYNC_IGNORE_FILE}"
  )

  run_timed "sync.rsync_datasystem" \
    rsync "${RSYNC_COMMON_OPTS[@]}" "${LOCAL_DS}/" "${REMOTE}:${REMOTE_DS_RESOLVED}/"

  run_timed "sync.rsync_vibe" \
    rsync "${RSYNC_COMMON_OPTS[@]}" "${LOCAL_VIBE}/" "${REMOTE}:${REMOTE_VIBE_RESOLVED}/"
else
  echo "[sync] Skipped (--skip-sync)"
fi

REMOTE_BUILD_DIR="${REMOTE_DS_RESOLVED%/}/${BUILD_DIR_REL}"

run_timed "remote.workflow" ssh "${REMOTE}" \
  "REMOTE_DS='${REMOTE_DS_RESOLVED}' REMOTE_VIBE='${REMOTE_VIBE_RESOLVED}' REMOTE_BUILD_DIR='${REMOTE_BUILD_DIR}' DS_OPENSOURCE_DIR='${REMOTE_OPENSOURCE_DIR_RESOLVED}' INSTALL_DEPS='${INSTALL_DEPS}' SKIP_CTEST='${SKIP_CTEST}' SKIP_VALIDATE='${SKIP_VALIDATE}' SKIP_RUN_EXAMPLE='${SKIP_RUN_EXAMPLE}' SKIP_WHEEL_INSTALL='${SKIP_WHEEL_INSTALL}' BUILD_JOBS='${BUILD_JOBS}' CTEST_JOBS='${CTEST_JOBS}' BUILD_HETERO='${BUILD_HETERO}' BUILD_PERF='${BUILD_PERF}' BUILD_INCREMENT='${BUILD_INCREMENT}' VALIDATE_URMA_TCP_LOGS='${VALIDATE_URMA_TCP_LOGS}' URMA_LOG_PATH='${REMOTE_URMA_LOG_PATH_RESOLVED}' bash -s" <<'EOF'
set -euo pipefail

TIMING_REPORT=""
WORKFLOW_STARTED_AT="$(date +%s)"

log_info() {
  echo "[$(date '+%F %T')] $*"
}

run_timed() {
  local step="$1"
  shift
  local started_at ended_at elapsed
  started_at="$(date +%s)"
  log_info "[start] ${step}"
  if "$@"; then
    ended_at="$(date +%s)"
    elapsed="$((ended_at - started_at))"
    log_info "[done] ${step} (${elapsed}s)"
    TIMING_REPORT+="${step}|${elapsed}|OK"$'\n'
  else
    ended_at="$(date +%s)"
    elapsed="$((ended_at - started_at))"
    log_info "[fail] ${step} (${elapsed}s)"
    TIMING_REPORT+="${step}|${elapsed}|FAIL"$'\n'
    return 1
  fi
}

print_timing_report() {
  local total_elapsed
  total_elapsed="$(( $(date +%s) - WORKFLOW_STARTED_AT ))"
  echo
  echo "== remote timing summary =="
  printf '%-44s %-10s %-6s\n' "STEP" "ELAPSED" "STATUS"
  while IFS='|' read -r step elapsed status; do
    [[ -z "${step}" ]] && continue
    printf '%-44s %-10ss %-6s\n' "${step}" "${elapsed}" "${status}"
  done <<< "${TIMING_REPORT}"
  printf '%-44s %-10ss %-6s\n' "workflow.total" "${total_elapsed}" "OK"
}

trap print_timing_report EXIT

run_timed "preflight.python_version" python3 --version
run_timed "preflight.uname_s" uname -s
run_timed "preflight.uname_m" uname -m
run_timed "preflight.glibc" bash -lc "ldd --version | head -n 1"

if [[ "${INSTALL_DEPS}" == "1" ]]; then
  log_info "[deps] Installing build dependencies on remote host..."
  if command -v dnf >/dev/null 2>&1; then
    run_timed "deps.install.dnf" sudo dnf install -y \
      gcc gcc-c++ make cmake pkgconf-pkg-config \
      python3 python3-pip python3-devel python3-wheel \
      git wget curl tar which openssl-devel zlib-devel libstdc++-devel \
      patch autoconf automake libtool perl-FindBin net-tools
  elif command -v apt-get >/dev/null 2>&1; then
    run_timed "deps.install.apt_update" sudo apt-get update
    run_timed "deps.install.apt_packages" sudo apt-get install -y \
      build-essential cmake ninja-build pkg-config \
      python3 python3-pip python3-dev python3-wheel \
      git wget curl tar \
      libssl-dev zlib1g-dev \
      patch autoconf automake libtool perl net-tools
  else
    echo "No supported package manager found (dnf/apt-get)." >&2
    exit 1
  fi
fi

if ! command -v etcd >/dev/null 2>&1; then
  log_info "[deps] etcd not found, installing standalone binary..."
  run_timed "deps.install.etcd_binary" bash -lc "
    set -euo pipefail
    ETCD_VER='v3.5.15'
    ARCHIVE=\"/tmp/etcd-\${ETCD_VER}-linux-amd64.tar.gz\"
    curl -fsSL -o \"\${ARCHIVE}\" \"https://github.com/etcd-io/etcd/releases/download/\${ETCD_VER}/etcd-\${ETCD_VER}-linux-amd64.tar.gz\"
    tar -xzf \"\${ARCHIVE}\" -C /tmp
    sudo install -m 0755 \"/tmp/etcd-\${ETCD_VER}-linux-amd64/etcd\" /usr/local/bin/etcd
    sudo install -m 0755 \"/tmp/etcd-\${ETCD_VER}-linux-amd64/etcdctl\" /usr/local/bin/etcdctl
  "
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
if [[ "${BUILD_HETERO}" != "on" && "${BUILD_HETERO}" != "off" ]]; then
  echo "Invalid BUILD_HETERO=${BUILD_HETERO}, expected on/off" >&2
  exit 2
fi
if [[ "${BUILD_PERF}" != "on" && "${BUILD_PERF}" != "off" ]]; then
  echo "Invalid BUILD_PERF=${BUILD_PERF}, expected on/off" >&2
  exit 2
fi
if [[ "${BUILD_INCREMENT}" != "on" && "${BUILD_INCREMENT}" != "off" ]]; then
  echo "Invalid BUILD_INCREMENT=${BUILD_INCREMENT}, expected on/off" >&2
  exit 2
fi
if [[ "${VALIDATE_URMA_TCP_LOGS}" != "0" && "${VALIDATE_URMA_TCP_LOGS}" != "1" ]]; then
  echo "Invalid VALIDATE_URMA_TCP_LOGS=${VALIDATE_URMA_TCP_LOGS}, expected 0/1" >&2
  exit 2
fi
log_info "Parallel jobs: build=${BUILD_JOBS}, ctest=${CTEST_JOBS}"
log_info "Build mode: incremental=${BUILD_INCREMENT}"

# If existing cache points to a different third-party directory, force
# a fresh CMake configure so DS_OPENSOURCE_DIR can take effect.
if [[ -f "${REMOTE_BUILD_DIR}/CMakeCache.txt" ]]; then
  cached_opensource_dir="$(
    sed -n 's/^DS_OPENSOURCE_DIR:PATH=//p' "${REMOTE_BUILD_DIR}/CMakeCache.txt" | tail -n 1
  )"
  if [[ -n "${cached_opensource_dir}" && "${cached_opensource_dir}" != "${DS_OPENSOURCE_DIR}" ]]; then
    log_info "[cache] DS_OPENSOURCE_DIR changed:"
    log_info "[cache]   old=${cached_opensource_dir}"
    log_info "[cache]   new=${DS_OPENSOURCE_DIR}"
    log_info "[cache] removing stale CMake cache to avoid third-party fallback rebuilds"
    rm -f "${REMOTE_BUILD_DIR}/CMakeCache.txt"
  fi
fi

cd "${DS}"
export JOBS="${BUILD_JOBS}"
run_timed "build.build_sh" bash build.sh -t build -B "${REMOTE_BUILD_DIR}" -X "${BUILD_HETERO}" -p "${BUILD_PERF}" -i "${BUILD_INCREMENT}" -j "${BUILD_JOBS}"

if [[ "${SKIP_CTEST}" != "1" ]]; then
  export CTEST_OUTPUT_ON_FAILURE=1
  run_timed "test.ctest" ctest --test-dir "${REMOTE_BUILD_DIR}" --output-on-failure --parallel "${CTEST_JOBS}"
else
  echo "[ctest] Skipped (--skip-ctest)"
fi

if [[ "${SKIP_VALIDATE}" != "1" ]]; then
  run_timed "test.validate_kv_executor" bash "${VIBE}/scripts/testing/verify/validate_kv_executor.sh" --skip-build "${REMOTE_BUILD_DIR}"
else
  echo "[validate] Skipped (--skip-validate)"
fi

if [[ "${SKIP_RUN_EXAMPLE}" != "1" ]]; then
  run_timed "test.run_example" bash build.sh -t run_example
else
  echo "[run_example] Skipped (--skip-run-example)"
fi

if [[ "${SKIP_WHEEL_INSTALL}" != "1" ]]; then
  WHEEL_PATH="$(find "${DS}/output" "${DS}/build" -maxdepth 6 -name 'openyuanrong_datasystem-*.whl' 2>/dev/null | head -n 1 || true)"
  if [[ -n "${WHEEL_PATH}" ]]; then
    run_timed "wheel.install" python3 -m pip install --user "${WHEEL_PATH}"
    if command -v dscli >/dev/null 2>&1; then
      run_timed "wheel.dscli_version" dscli --version
    else
      echo "dscli not in PATH yet (usually in ~/.local/bin)."
    fi
  else
    echo "No wheel found under ${DS}/output or ${DS}/build; skip install."
  fi
else
  echo "[wheel] Skipped (--skip-wheel-install)"
fi

if [[ "${VALIDATE_URMA_TCP_LOGS}" == "1" ]]; then
  if [[ -n "${URMA_LOG_PATH}" ]]; then
    CHECK_FAIL_MSG="Specified URMA_LOG_PATH does not exist: ${URMA_LOG_PATH}"
    [[ -e "${URMA_LOG_PATH}" ]] || { echo "${CHECK_FAIL_MSG}" >&2; exit 1; }
    run_timed "test.validate_urma_tcp_logs" \
      bash "${VIBE}/scripts/testing/verify/validate_urma_tcp_observability_logs.sh" "${URMA_LOG_PATH}"
  else
    CANDIDATE_LOG_PATHS=(
      "${DS}/log"
      "${DS}/logs"
      "${REMOTE_BUILD_DIR}/log"
      "${REMOTE_BUILD_DIR}/logs"
      "${DS}/build/log"
      "${DS}/build/logs"
    )
    EXISTING_LOG_PATHS=()
    for p in "${CANDIDATE_LOG_PATHS[@]}"; do
      if [[ -e "${p}" ]]; then
        EXISTING_LOG_PATHS+=("${p}")
      fi
    done
    if [[ "${#EXISTING_LOG_PATHS[@]}" -eq 0 ]]; then
      echo "Cannot auto-detect URMA log path; use --urma-log-path <path>." >&2
      exit 1
    fi
    run_timed "test.validate_urma_tcp_logs" \
      bash "${VIBE}/scripts/testing/verify/validate_urma_tcp_observability_logs.sh" "${EXISTING_LOG_PATHS[@]}"
  fi
else
  echo "[urma-log-validate] Skipped (enable with --validate-urma-tcp-logs)"
fi

log_info "Remote build workflow finished."
EOF

print_timing_report
