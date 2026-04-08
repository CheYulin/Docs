#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/datasystem_root.sh
. "${SCRIPT_DIR}/../lib/datasystem_root.sh"
BUILD_DIR="${ROOT_DIR}/build"
OUT_DIR="${ROOT_DIR}/.third_party/brpc_st_compat"
JOBS="${JOBS:-$(nproc)}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir)
            BUILD_DIR="$2"
            shift 2
            ;;
        --out-dir)
            OUT_DIR="$2"
            shift 2
            ;;
        --jobs)
            JOBS="$2"
            shift 2
            ;;
        *)
            echo "Unknown arg: $1"
            exit 1
            ;;
    esac
done

if [[ ! -f "${BUILD_DIR}/CMakeCache.txt" ]]; then
    echo "Missing ${BUILD_DIR}/CMakeCache.txt, please configure project first."
    exit 1
fi

parse_cache() {
    python3 - "$BUILD_DIR/CMakeCache.txt" <<'PY'
import sys
from pathlib import Path
cache = Path(sys.argv[1]).read_text(errors="ignore").splitlines()
kv = {}
for line in cache:
    if not line or line.startswith("//") or line.startswith("#") or "=" not in line:
        continue
    key_t, value = line.split("=", 1)
    key = key_t.split(":", 1)[0]
    kv[key] = value
pb_dir = kv.get("Protobuf_DIR", "")
absl_dir = kv.get("absl_DIR", "")
if not pb_dir:
    print("ERR:Protobuf_DIR")
    sys.exit(2)
pb_root = str(Path(pb_dir).parents[2])
absl_root = str(Path(absl_dir).parents[2]) if absl_dir else ""
openssl_lib = kv.get("OPENSSL_CRYPTO_LIBRARY", "")
openssl_root = str(Path(openssl_lib).parents[1]) if openssl_lib else ""
print(pb_root)
print(absl_root)
print(openssl_root)
PY
}

mapfile -t CACHE_INFO < <(parse_cache)
PROTOBUF_ROOT="${CACHE_INFO[0]}"
ABSL_ROOT="${CACHE_INFO[1]}"
OPENSSL_ROOT="${CACHE_INFO[2]}"

PROTOC="${PROTOBUF_ROOT}/bin/protoc"
if [[ ! -x "${PROTOC}" ]]; then
    echo "Cannot find protoc at ${PROTOC}"
    exit 1
fi
if [[ -n "${ABSL_ROOT}" && ! -d "${PROTOBUF_ROOT}/include/absl" ]]; then
    ln -s "${ABSL_ROOT}/include/absl" "${PROTOBUF_ROOT}/include/absl"
fi

WORK_DIR="${OUT_DIR}/src"
INSTALL_DIR="${OUT_DIR}/install"
mkdir -p "${WORK_DIR}" "${INSTALL_DIR}"

clone_or_update() {
    local repo="$1"
    local dir="$2"
    local rev="$3"
    if [[ ! -d "${dir}/.git" ]]; then
        git clone --depth 1 "${repo}" "${dir}"
    fi
    git -C "${dir}" fetch --depth 1 origin "${rev}"
    git -C "${dir}" checkout --force FETCH_HEAD
}

build_cmake_proj() {
    local src="$1"
    local bld="$2"
    shift 2
    cmake -S "${src}" -B "${bld}" "$@"
    cmake --build "${bld}" -j "${JOBS}"
    cmake --install "${bld}"
}

clone_or_update https://github.com/gflags/gflags.git "${WORK_DIR}/gflags" v2.2.2
build_cmake_proj "${WORK_DIR}/gflags" "${WORK_DIR}/gflags/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="${INSTALL_DIR}" \
    -DBUILD_SHARED_LIBS=ON \
    -DBUILD_STATIC_LIBS=OFF

clone_or_update https://github.com/google/leveldb.git "${WORK_DIR}/leveldb" 1.23
build_cmake_proj "${WORK_DIR}/leveldb" "${WORK_DIR}/leveldb/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="${INSTALL_DIR}" \
    -DBUILD_SHARED_LIBS=ON \
    -DLEVELDB_BUILD_TESTS=OFF \
    -DLEVELDB_BUILD_BENCHMARKS=OFF

# Pinned release tag for reproducible st reference builds.
clone_or_update https://github.com/apache/brpc.git "${WORK_DIR}/brpc" 1.16.0

PREFIX_PATHS="${INSTALL_DIR};${PROTOBUF_ROOT}"
if [[ -n "${ABSL_ROOT}" ]]; then
    PREFIX_PATHS="${PREFIX_PATHS};${ABSL_ROOT}"
fi
if [[ -n "${OPENSSL_ROOT}" ]]; then
    PREFIX_PATHS="${PREFIX_PATHS};${OPENSSL_ROOT}"
fi

BRPC_LD_PATH="${PROTOBUF_ROOT}/lib:${INSTALL_DIR}/lib"
if [[ -n "${ABSL_ROOT}" ]]; then
    BRPC_LD_PATH="${ABSL_ROOT}/lib:${BRPC_LD_PATH}"
fi
if [[ -n "${OPENSSL_ROOT}" ]]; then
    BRPC_LD_PATH="${OPENSSL_ROOT}/lib:${BRPC_LD_PATH}"
fi

LD_LIBRARY_PATH="${BRPC_LD_PATH}:${LD_LIBRARY_PATH:-}" \
CPPFLAGS="-I${ABSL_ROOT}/include ${CPPFLAGS:-}" \
CXXFLAGS="-I${ABSL_ROOT}/include ${CXXFLAGS:-}" \
build_cmake_proj "${WORK_DIR}/brpc" "${WORK_DIR}/brpc/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="${INSTALL_DIR}" \
    -DBUILD_SHARED_LIBS=ON \
    -DBUILD_UNIT_TESTS=OFF \
    -DWITH_GLOG=OFF \
    -DWITH_MESALINK=OFF \
    -DCMAKE_PREFIX_PATH="${PREFIX_PATHS}" \
    -DProtobuf_DIR="${PROTOBUF_ROOT}/lib/cmake/protobuf" \
    -Dabsl_DIR="${ABSL_ROOT}/lib/cmake/absl" \
    -DGFLAGS_ROOT_DIR="${INSTALL_DIR}" \
    -DLEVELDB_ROOT="${INSTALL_DIR}"

LD_PATH="${PROTOBUF_ROOT}/lib:${INSTALL_DIR}/lib"
if [[ -n "${ABSL_ROOT}" ]]; then
    LD_PATH="${ABSL_ROOT}/lib:${LD_PATH}"
fi
if [[ -n "${OPENSSL_ROOT}" ]]; then
    LD_PATH="${OPENSSL_ROOT}/lib:${LD_PATH}"
fi

LD_LIBRARY_PATH="${LD_PATH}" "${PROTOC}" \
    --cpp_out="${ROOT_DIR}/tests/st/client/kv_cache" \
    --proto_path="${ROOT_DIR}/tests/st/client/kv_cache" \
    "${ROOT_DIR}/tests/st/client/kv_cache/kv_brpc_bridge.proto"

echo
echo "Bootstrap done."
echo "Use with:"
echo "cmake -S ${ROOT_DIR} -B ${BUILD_DIR} -DENABLE_BRPC_ST_REFERENCE=ON -DBRPC_ST_ROOT=${INSTALL_DIR}"
