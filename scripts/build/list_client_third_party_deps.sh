#!/usr/bin/env bash
# Map client DSO / test binary NEEDED entries to build/_deps/*-src (CMake FetchContent).
# Use output to scope third-party review: only these deps + client call graph; look for lock+IO.
# Usage (from repo root):
#   bash scripts/build/list_client_third_party_deps.sh [--build-dir build] [--target lib|test|both]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
TARGET="both"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/build/list_client_third_party_deps.sh [--build-dir DIR] [--target lib|test|both]

Prints:
  - readelf NEEDED for libdatasystem.so and/or ds_st_kv_cache
  - ldd (with plain paths; set LD_LIBRARY_PATH yourself if not found)
  - Suggested build/_deps/*-src directories for vendored source browsing

Then audit only call-reachable code for mutex+IO (see plans/.../05 §1.1).

EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-dir) BUILD_DIR="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1"; usage; exit 1 ;;
  esac
done

LIB_SO="${BUILD_DIR}/src/datasystem/client/libdatasystem.so"
TEST_BIN="${BUILD_DIR}/tests/st/ds_st_kv_cache"
DEPS_ROOT="${BUILD_DIR}/_deps"

section() { printf '\n=== %s ===\n' "$1"; }

print_one() {
  local label="$1" path="$2"
  if [[ ! -e "$path" ]]; then
    echo "[skip] missing: $path"
    return
  fi
  section "$label: readelf -d NEEDED"
  readelf -d "$path" 2>/dev/null | grep NEEDED || true
  section "$label: ldd"
  ldd "$path" 2>/dev/null || true
}

section "Third-party source roots (CMake FetchContent)"
if [[ -d "$DEPS_ROOT" ]]; then
  printf '%s\n' \
    "  grpc-src          -> gRPC C++ core + wrapped deps (see grpc-src/third_party)" \
    "  protobuf-src      -> protobuf C++ runtime" \
    "  zeromq-src        -> libzmq" \
    "  openssl-src       -> OpenSSL (libssl/libcrypto)" \
    "  absl-src          -> Abseil (gRPC/protobuf transitive)" \
    "  zlib-src          -> zlib" \
    "  spdlog-src        -> spdlog (ds-spdlog)" \
    "  tbb-src           -> oneTBB" \
    "  securec-src       -> libsecurec" \
    "  c-ares-src        -> c-ares (often used by gRPC)" \
    "  curl-src          -> libcurl (often test/OBS stack only)"
  echo ""
  echo "Tip: deep reads for lock+IO in gRPC start under grpc-src/src/core/ (poll, epoll, tcp, ssl)."
  echo "     ZeroMQ: zeromq-src/src/ (socket_engine, tcp, poll)."
else
  echo "[warn] ${DEPS_ROOT} not found — configure/build once so FetchContent populates _deps."
fi

case "$TARGET" in
  lib)
    print_one "libdatasystem.so" "$LIB_SO"
    ;;
  test)
    print_one "ds_st_kv_cache" "$TEST_BIN"
    ;;
  both)
    print_one "libdatasystem.so" "$LIB_SO"
    print_one "ds_st_kv_cache" "$TEST_BIN"
    ;;
  *)
    echo "bad --target"; exit 1 ;;
esac

section "SDK client-only third-party set (from libdatasystem.so ldd)"
echo "Typically: grpc++/grpc/gpr, protobuf, zeromq, openssl, abseil, zlib, spdlog, tbb, securec."
echo "ds_st_kv_cache adds: brpc (if ENABLE_BRPC_ST_REFERENCE), curl, obs, metastore .so — treat as ST-only extras."
