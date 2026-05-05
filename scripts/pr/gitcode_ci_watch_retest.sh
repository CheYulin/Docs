#!/usr/bin/env bash
# Poll a GitCode MR for CI labels; on ci_processing -> ci_failed transition, post /retest as an MR comment.
# Requires: GITCODE_TOKEN (Bearer), curl, python3.
#
# Usage:
#   export GITCODE_TOKEN=...
#   PR_NUMBER=793 bash scripts/pr/gitcode_ci_watch_retest.sh
#
# Optional env:
#   OWNER=openeuler REPO=yuanrong-datasystem INTERVAL_SEC=600 STATE_FILE=path ONCE=1

set -euo pipefail

OWNER="${OWNER:-openeuler}"
REPO="${REPO:-yuanrong-datasystem}"
PR_NUMBER="${PR_NUMBER:?set PR_NUMBER (merge request number)}"
INTERVAL_SEC="${INTERVAL_SEC:-600}"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/gitcode-pr-watch"
STATE_FILE="${STATE_FILE:-${STATE_DIR}/${OWNER}_${REPO}_${PR_NUMBER}.last_ci_phase}"

[[ -n "${GITCODE_TOKEN:-}" ]] || {
  echo "error: GITCODE_TOKEN is not set" >&2
  exit 1
}

mkdir -p "$(dirname "$STATE_FILE")"

ci_phase() {
  python3 -c '
import json, sys
raw = sys.stdin.read()
data = json.loads(raw)
labels = data.get("labels", []) if isinstance(data, dict) else []
names = [x.get("name", "") for x in labels]
if "ci_failed" in names:
    print("failed")
elif "ci_processing" in names:
    print("processing")
elif "ci_successful" in names:
    print("successful")
else:
    print("unknown")
'
}

fetch_pr() {
  curl -sS -H "Authorization: Bearer ${GITCODE_TOKEN}" \
    "https://api.gitcode.com/api/v5/repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}"
}

post_retest() {
  local payload
  payload="$(python3 <<'PY'
import json
print(json.dumps({"body": "/retest\n\n(auto watch: ci_processing -> ci_failed)"}))
PY
)"
  curl -sS -X POST -H "Authorization: Bearer ${GITCODE_TOKEN}" \
    -H "Content-Type: application/json; charset=utf-8" \
    -d "${payload}" \
    "https://api.gitcode.com/api/v5/repos/${OWNER}/${REPO}/pulls/${PR_NUMBER}/comments"
}

read_prev() {
  if [[ -f "$STATE_FILE" ]]; then
    tr -d '\n' <"$STATE_FILE"
  else
    echo ""
  fi
}

write_prev() {
  printf '%s' "$1" >"$STATE_FILE"
}

poll_once() {
  local json phase prev err_msg
  json="$(fetch_pr)"
  err_msg="$(python3 -c '
import json, sys
d = json.loads(sys.stdin.read())
if isinstance(d, dict) and d.get("error_code"):
    print(d.get("error_message") or "unknown api error")
' <<<"$json")"
  if [[ -n "${err_msg}" ]]; then
    echo "$(date -Is) PR#${PR_NUMBER} api error: ${err_msg}" >&2
    return 0
  fi
  phase="$(printf '%s' "$json" | ci_phase)"
  prev="$(read_prev)"
  echo "$(date -Is) PR#${PR_NUMBER} ci_phase=${phase} prev=${prev:-∅}"

  if [[ -n "$prev" && "$prev" == "processing" && "$phase" == "failed" ]]; then
    echo "$(date -Is) posting /retest comment..."
    local resp
    resp="$(post_retest)"
    echo "$(date -Is) response: ${resp:0:300}"
  fi

  if [[ "$phase" != "unknown" ]]; then
    write_prev "$phase"
  fi
}

if [[ -n "${ONCE:-}" ]]; then
  poll_once
  exit 0
fi

while true; do
  poll_once || true
  sleep "${INTERVAL_SEC}"
done
