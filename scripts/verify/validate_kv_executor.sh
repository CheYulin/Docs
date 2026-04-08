#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
REPO_ROOT="${ROOT_DIR}"
SKIP_BUILD=0
POS_ARGS=()

usage() {
  cat <<'EOF'
Usage:
  bash scripts/verify/validate_kv_executor.sh [--skip-build] [BUILD_DIR]

  --skip-build   Do not run cmake --build (only ctest + src audit). Use when the
                 tree is already built to avoid re-triggering third_party / full deps.
  BUILD_DIR      CMake build directory (default: <datasystem>/build)

Environment:
  JOBS                    Parallel build jobs (default: 8)
  DATASYSTEM_ROOT         When running this copy from vibe-coding-files, points at yuanrong-datasystem
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      POS_ARGS+=("$1")
      shift
      ;;
  esac
done

BUILD_DIR="${POS_ARGS[0]:-${REPO_ROOT}/build}"
JOBS="${JOBS:-8}"
ST_BIN="${BUILD_DIR}/tests/st/ds_st_kv_cache"

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  echo "[1/3] Build ds_st_kv_cache"
  cmake --build "${BUILD_DIR}" --target ds_st_kv_cache -j "${JOBS}"
else
  echo "[1/3] Skip build (--skip-build)"
  if [[ ! -x "${ST_BIN}" ]]; then
    echo "Missing or non-executable: ${ST_BIN}" >&2
    echo "Run without --skip-build once, or pass a BUILD_DIR where ds_st_kv_cache exists." >&2
    exit 1
  fi
fi

echo "[2/3] Run KVClientExecutorRuntimeE2ETest suite by ctest"
ctest --test-dir "${BUILD_DIR}" --output-on-failure -R "KVClientExecutorRuntimeE2ETest"

echo "[3/3] Audit forbidden keywords in src"
python3 - "${REPO_ROOT}/src" <<'PY'
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
pat = re.compile(r"\b(brpc|bthread)\b", re.IGNORECASE)
matches = []

for f in src.rglob("*"):
    if not f.is_file():
        continue
    if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".so", ".a", ".o"}:
        continue
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if pat.search(line):
            matches.append((f, i, line.strip()))
            if len(matches) >= 20:
                break
    if len(matches) >= 20:
        break

if matches:
    print("Found forbidden keywords in src:")
    for f, i, line in matches:
        print(f"  {f}:{i}: {line}")
    sys.exit(2)

print("No forbidden keywords found in src.")
PY

echo "Validation passed."
