#!/usr/bin/env bash
# Common utility functions used across multiple scripts.

# Print a timestamped info message.
log_info() {
  echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $*"
}

# Print a timestamped error message.
log_error() {
  echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

# Generate a UTC timestamp suitable for directory names: YYYYMMDD_HHMMSS
stamp_utc() {
  date -u '+%Y%m%d_%H%M%S'
}

# Require a variable to be non-empty, print error and exit 1 otherwise.
require_var() {
  local name="$1"
  local val="$2"
  if [[ -z "$val" ]]; then
    echo "${name} must be set and non-empty" >&2
    exit 1
  fi
}

# Check if a command exists.
cmd_exists() {
  command -v "$1" >/dev/null 2>&1
}
