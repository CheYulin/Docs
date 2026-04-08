#!/usr/bin/env bash
set -euo pipefail
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
# shellcheck source=../lib/vibe_coding_root.sh
. "${SCRIPT_DIR}/../lib/vibe_coding_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
FILTER="${FILTER:-KVClientExecutorRuntimeE2ETest.*}"
OUT_DIR="${VIBE_CODING_ROOT}/workspace/observability/bpftrace"
BT_SCRIPT="${SCRIPT_DIR}/bpftrace/kv_lock_io_stacks.bt"

usage() {
    cat <<'EOF'
Usage:
  sudo bash scripts/perf/trace_kv_lock_io_bpftrace.sh [options]

bpftrace must run as root. Do not put your sudo password in the repo (e.g. a "passwd"
file) or pipe it to sudo — use an interactive sudo session, or configure a narrowly
scoped NOPASSWD rule for bpftrace via visudo.

Options:
  --build-dir <dir>   Build directory (default: ./build)
  --filter <expr>     GTest filter expression
  --out-dir <dir>     Output directory for bpftrace artifacts (default: workspace/observability/bpftrace under vibe-coding-files)
  -h, --help          Show help

Better symbols:
  BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh
  (needs llvm-symbolizer + debug build; see scripts/perf/bpftrace/RUN_SYMBOLS.txt)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --filter)
            FILTER="$2"
            shift 2
            ;;
        --out-dir)
            OUT_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown arg: $1"
            usage
            exit 1
            ;;
    esac
done

# Relative build dir: datasystem root. Relative out dir: vibe-coding-files root (artifact workspace).
if [[ "${BUILD_DIR}" != /* ]]; then
    BUILD_DIR="${ROOT_DIR}/${BUILD_DIR}"
fi
if [[ "${OUT_DIR}" != /* ]]; then
    OUT_DIR="${VIBE_CODING_ROOT}/${OUT_DIR}"
fi

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "[error] bpftrace requires root. Run: sudo bash scripts/perf/trace_kv_lock_io_bpftrace.sh ..." >&2
    echo "[error] Do not store sudo passwords in the repository." >&2
    exit 1
fi

TEST_BIN="${BUILD_DIR}/tests/st/ds_st_kv_cache"
TEST_DESC="${BUILD_DIR}/tests/st/ds_st_kv_cache_tests.cmake"
[[ -x "${TEST_BIN}" ]] || { echo "Missing test binary: ${TEST_BIN}"; exit 1; }
[[ -f "${TEST_DESC}" ]] || { echo "Missing test descriptor: ${TEST_DESC}"; exit 1; }
[[ -f "${BT_SCRIPT}" ]] || { echo "Missing bpftrace script: ${BT_SCRIPT}"; exit 1; }

mkdir -p "${OUT_DIR}"
TS="$(date +%Y%m%d_%H%M%S)"
OUT_TXT="${OUT_DIR}/trace_${TS}_stacks.txt"
PID_FILE="${OUT_DIR}/trace_${TS}.pid"
MAPS_FILE="${OUT_DIR}/trace_${TS}_maps.txt"
CMD_FILE="${OUT_DIR}/trace_${TS}_cmd.sh"
MAPS_BG_PID_FILE="${OUT_DIR}/trace_${TS}_maps_bg.pid"

LD_PATH="$(
python3 - "${TEST_DESC}" "${TEST_BIN}" <<'PY'
import pathlib
import sys
text = pathlib.Path(sys.argv[1]).read_text(errors='ignore')
binary = sys.argv[2]
start = text.find("LD_LIBRARY_PATH=")
marker = f"]==] {binary}"
end = text.find(marker, start)
if start < 0 or end < 0:
    raise SystemExit(2)
print(text[start + len("LD_LIBRARY_PATH="):end], end="")
PY
)"

echo "[INFO] build_dir=${BUILD_DIR}"
echo "[INFO] filter=${FILTER}"
echo "[INFO] out=${OUT_TXT}"
echo "[INFO] pid_file=${PID_FILE}"
echo "[INFO] maps_file=${MAPS_FILE}"
echo "[INFO] cmd_file=${CMD_FILE}"
echo "[INFO] maps_bg_pid_file=${MAPS_BG_PID_FILE}"
echo "[INFO] ROOT_DIR=${ROOT_DIR} (from script path; cwd does not need to be repo root if you invoke this script by absolute path)"
echo "[INFO] running bpftrace -c (gtest runs inside traced child; often 1–2+ minutes — not hung)"
echo "[INFO] live output below is also written to: ${OUT_TXT}"
if [[ "${BPFTRACE_SYMBOL_ENV:-}" == "1" && -f "${SCRIPT_DIR}/bpftrace/env_for_symbols.sh" ]]; then
    # shellcheck disable=SC1090
    source "${SCRIPT_DIR}/bpftrace/env_for_symbols.sh"
fi

cat > "${CMD_FILE}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
echo \$\$ > "${PID_FILE}"
exec env LD_LIBRARY_PATH="${LD_PATH}" "${TEST_BIN}" --gtest_filter="${FILTER}" --gtest_color=no
EOF
chmod +x "${CMD_FILE}"

# Background helper: once pid appears, snapshot /proc/<pid>/maps while process is alive.
(
  for _ in $(seq 1 600); do
    if [[ -s "${PID_FILE}" ]]; then
      PID_VAL="$(tr -dc '0-9' < "${PID_FILE}" || true)"
      if [[ -n "${PID_VAL}" && -r "/proc/${PID_VAL}/maps" ]]; then
        cp "/proc/${PID_VAL}/maps" "${MAPS_FILE}" 2>/dev/null || true
        exit 0
      fi
    fi
    sleep 0.1
  done
) &
echo $! > "${MAPS_BG_PID_FILE}"

bpftrace "${BT_SCRIPT}" -c "bash ${CMD_FILE}" \
  2>&1 | tee "${OUT_TXT}"

# Stop background maps helper if still alive.
if [[ -s "${MAPS_BG_PID_FILE}" ]]; then
    BG_PID="$(tr -dc '0-9' < "${MAPS_BG_PID_FILE}" || true)"
    if [[ -n "${BG_PID}" ]]; then
        kill "${BG_PID}" 2>/dev/null || true
    fi
fi

# Best-effort maps snapshot for post symbolization (may be missing if process exits quickly).
if [[ -f "${PID_FILE}" ]]; then
    PID_VAL="$(tr -dc '0-9' < "${PID_FILE}" || true)"
    if [[ -n "${PID_VAL}" && -r "/proc/${PID_VAL}/maps" ]]; then
        cp "/proc/${PID_VAL}/maps" "${MAPS_FILE}" 2>/dev/null || true
    fi
fi

# If invoked via sudo, give the output tree back to the invoking user (avoid root-owned workspace/observability/bpftrace).
if [[ -n "${SUDO_UID:-}" ]]; then
    chown -R "${SUDO_UID}:${SUDO_GID:-${SUDO_UID}}" "${OUT_DIR}" 2>/dev/null || true
fi

echo "[DONE] bpftrace stack report: ${OUT_TXT}"
