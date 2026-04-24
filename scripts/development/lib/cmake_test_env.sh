#!/usr/bin/env bash
# Extract LD_LIBRARY_PATH from a CMake test descriptor .cmake file.
# Used by trace/perf scripts that need to run test binaries.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "${SCRIPT_DIR}/cmake_test_env.sh"
#
#   extract_ld_library_path <cmake_file> <binary_name>
#     - reads <cmake_file>, finds the entry for <binary_name>,
#       extracts the LD_LIBRARY_PATH value between 'LD_LIBRARY_PATH=' and ']==]'
#     - prints the path, or empty if not found

set -euo pipefail

: "${SCRIPT_DIR:?SCRIPT_DIR must be set before sourcing cmake_test_env.sh}"

extract_ld_library_path() {
  local cmake_file="${1:?extract_ld_library_path: cmake_file required}"
  local binary="${2:?extract_ld_library_path: binary name required}"

  python3 - "${cmake_file}" "${binary}" <<'PY'
import pathlib, sys

cmake_path = pathlib.Path(sys.argv[1])
binary_name = sys.argv[2]

text = cmake_path.read_text(errors='ignore')
marker = f"]{binary_name}]==]"
if marker not in text:
    sys.exit(0)

# Find the LD_LIBRARY_PATH=value between marker and ]==]
start = text.index(marker) + len(marker)
end = text.index(']==]', start)
line = text[start:end]
kv = line.split('LD_LIBRARY_PATH=', 1)
if len(kv) < 2:
    sys.exit(0)
value = kv[1].strip()
print(value, end='')
PY
}
