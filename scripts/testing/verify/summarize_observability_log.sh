#!/usr/bin/env bash
# =============================================================================
# summarize_observability_log.sh
#
# Purpose:
#   Companion script to docs/observable/07-pr-metrics-fault-localization.md.
#   Given one or more log files (worker.log / sdk.log / captured stderr) from
#   a datasystem run, emit a compact table that summarises:
#     (a) presence of the periodic "Metrics Summary" block
#     (b) counts of every KV / ZMQ metric name that appears in the log
#     (c) counts of every structured log tag introduced by PR #583 / #588
#     (d) presence of ZmqMetricsFaultTest [FAULT INJECT] / [ISOLATION] markers
#
# Usage:
#   ./summarize_observability_log.sh <log> [<log> ...]
#
# Exit:
#   0 — ran successfully (regardless of whether tags were present)
#   2 — usage error
# =============================================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
  cat <<USAGE
Usage: $0 <logfile> [<logfile> ...]
Summarise metrics/tags produced by PR #583/#584/#586/#588.
USAGE
  exit 2
fi

LOGS=("$@")
for p in "${LOGS[@]}"; do
  if [[ ! -f "$p" && ! -d "$p" ]]; then
    echo "[error] not found: $p" >&2
    exit 2
  fi
done

# grep returns 1 on "no match", which fires pipefail; swallow with `|| true`.
count() {
  local pattern="$1"
  { grep -RhoE --binary-files=without-match "$pattern" "${LOGS[@]}" 2>/dev/null || true; } \
    | wc -l | tr -d ' '
}

delta_last() {
  local name="$1"
  { grep -RhE --binary-files=without-match "^${name}=\+-?[0-9]+" "${LOGS[@]}" 2>/dev/null || true; } \
    | tail -n 1 | sed -E "s/^${name}=//"
}

hist_last() {
  local name="$1"
  { grep -RhE --binary-files=without-match "^${name},count=\+[0-9]+,avg=" "${LOGS[@]}" 2>/dev/null || true; } \
    | tail -n 1 | sed -E "s/^${name},//"
}

banner() {
  printf '\n═══ %s ═══\n' "$1"
}

banner "0. Summary blocks"
printf '  Metrics Summary header lines  : %s\n' "$(count '^Metrics Summary, version=v0, cycle=[0-9]+')"
printf '  Total: segments               : %s\n' "$(count '^Total:$')"
printf '  Compare-with-previous segments: %s\n' "$(count '^Compare with [0-9]+ms before:$')"

banner "1. KV metrics — last delta (+N) in Compare segment"
KV_COUNTERS=(
  client_put_request_total
  client_put_error_total
  client_get_request_total
  client_get_error_total
  client_put_urma_write_total_bytes
  client_put_tcp_write_total_bytes
  client_get_urma_read_total_bytes
  client_get_tcp_read_total_bytes
  worker_to_client_total_bytes
  worker_from_client_total_bytes
)
KV_GAUGES=(worker_object_count worker_allocated_memory_size)
KV_HISTS=(
  client_rpc_create_latency
  client_rpc_publish_latency
  client_rpc_get_latency
  worker_rpc_create_meta_latency
  worker_rpc_query_meta_latency
  worker_rpc_get_remote_object_latency
  worker_process_create_latency
  worker_process_publish_latency
  worker_process_get_latency
  worker_urma_write_latency
  worker_tcp_write_latency
)

for name in "${KV_COUNTERS[@]}"; do
  v="$(delta_last "$name")"
  printf '  %-42s last Δ= %s\n' "$name" "${v:-<absent>}"
done
for name in "${KV_GAUGES[@]}"; do
  v="$(delta_last "$name")"
  printf '  %-42s last Δ= %s\n' "$name" "${v:-<absent>}"
done
for name in "${KV_HISTS[@]}"; do
  v="$(hist_last "$name")"
  printf '  %-42s last Δ= %s\n' "$name" "${v:-<absent>}"
done

banner "2. ZMQ metrics — last delta (+N) in Compare segment"
ZMQ_COUNTERS=(
  zmq_send_failure_total
  zmq_receive_failure_total
  zmq_send_try_again_total
  zmq_receive_try_again_total
  zmq_network_error_total
  zmq_gateway_recreate_total
  zmq_event_disconnect_total
  zmq_event_handshake_failure_total
)
ZMQ_HISTS=(
  zmq_send_io_latency
  zmq_receive_io_latency
  zmq_rpc_serialize_latency
  zmq_rpc_deserialize_latency
)
for name in "${ZMQ_COUNTERS[@]}"; do
  v="$(delta_last "$name")"
  printf '  %-42s last Δ= %s\n' "$name" "${v:-<absent>}"
done
for name in "${ZMQ_HISTS[@]}"; do
  v="$(hist_last "$name")"
  printf '  %-42s last Δ= %s\n' "$name" "${v:-<absent>}"
done
# Gauge: zmq_last_error_number (last observed value, not delta)
LAST_ERRNO=$(grep -RhE --binary-files=without-match '^zmq_last_error_number=-?[0-9]+' "${LOGS[@]}" 2>/dev/null \
  | tail -n 1 | sed -E 's/^zmq_last_error_number=//' || true)
printf '  %-42s current= %s\n' "zmq_last_error_number (Gauge)" "${LAST_ERRNO:-<absent>}"

banner "3. Structured log tags (PR #583 / #588)"
TAGS=(
  URMA_WAIT_TIMEOUT
  URMA_POLL_ERROR
  URMA_NEED_CONNECT
  URMA_RECREATE_JFS
  URMA_RECREATE_JFS_FAILED
  URMA_RECREATE_JFS_SKIP
  ZMQ_SEND_FAILURE_TOTAL
  ZMQ_RECEIVE_FAILURE_TOTAL
  ZMQ_RECV_TIMEOUT
  RPC_RECV_TIMEOUT
  RPC_SERVICE_UNAVAILABLE
  SOCK_CONN_WAIT_TIMEOUT
  REMOTE_SERVICE_WAIT_TIMEOUT
  TCP_CONNECT_RESET
  TCP_CONNECT_FAILED
  TCP_NETWORK_UNREACHABLE
  UDS_CONNECT_FAILED
  SHM_FD_TRANSFER_FAILED
)
TOTAL_TAG_HITS=0
for tag in "${TAGS[@]}"; do
  c="$(count "\[${tag}\]")"
  TOTAL_TAG_HITS=$(( TOTAL_TAG_HITS + c ))
  printf '  [%-30s] hits=%s\n' "$tag" "$c"
done
printf '\n  TOTAL tag hits: %s\n' "$TOTAL_TAG_HITS"

banner "4. Fault-injection markers (ZmqMetricsFaultTest-style)"
declare -A FAULT_PATTERNS=(
  ["[FAULT INJECT]"]='\[FAULT INJECT\]'
  ["[METRICS DUMP - Normal RPCs]"]='\[METRICS DUMP - Normal RPCs\]'
  ["[METRICS DUMP - Server Killed]"]='\[METRICS DUMP - Server Killed\]'
  ["[METRICS DUMP - Slow Server]"]='\[METRICS DUMP - Slow Server\]'
  ["[METRICS DUMP - High Load]"]='\[METRICS DUMP - High Load\]'
  ["[ISOLATION]"]='\[ISOLATION\]'
  ["[SELF-PROOF REPORT]"]='\[SELF-PROOF REPORT\]'
  ["CONCLUSION: (line start)"]='^CONCLUSION:'
)
# Stable display order (bash associative arrays don't preserve insertion order portably).
FAULT_LABELS=(
  "[FAULT INJECT]"
  "[METRICS DUMP - Normal RPCs]"
  "[METRICS DUMP - Server Killed]"
  "[METRICS DUMP - Slow Server]"
  "[METRICS DUMP - High Load]"
  "[ISOLATION]"
  "[SELF-PROOF REPORT]"
  "CONCLUSION: (line start)"
)
for label in "${FAULT_LABELS[@]}"; do
  c="$(count "${FAULT_PATTERNS[$label]}")"
  printf '  %-36s hits=%s\n' "$label" "$c"
done

banner "Done"
echo "  Tip: combine with docs/observable/07-pr-metrics-fault-localization.md §3 scenario table"
echo "  to map the non-zero deltas to a concrete fault hypothesis."
