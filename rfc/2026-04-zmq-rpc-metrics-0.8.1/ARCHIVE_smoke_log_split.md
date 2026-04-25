# Smoke: where `metrics_summary` is emitted (archived note, 2026-04-26)

## Design reference

See `sequence_diagram.puml`: client/stub path records `CLIENT_ENQUEUE` / `TO_STUB` / `SEND` and on response computes **client_queuing**, **stub_send**, **rpc_e2e**, **rpc_network**; worker path records **server_queue_wait**, **server_exec**, **server_reply**.

## Process split

| Metric (kv name) | Observed in | Log source for smoke |
|------------------|------------|------------------------|
| `zmq_client_*`, `zmq_rpc_e2e`, `zmq_rpc_network` | **Client** C++ (`RecordUnaryRpcLatencyMetrics`, stub) | Client process glog under `GOOGLE_LOG_DIR` |
| `zmq_server_*`, ZMQ I/O, ser/deser (typical) | **Worker** | `workers/worker-<port>/` (e.g. `datasystem_worker.INFO.log`) |

The global `metrics` registry is **per process**. Parsing only **worker** logs cannot show client-side flow metrics even when `ZmqRpcMetricsDiag` says `e2e=1` in the **client** log.

## Workbench change

- Each Python client subprocess sets `GOOGLE_LOG_DIR` and `GLOG_log_dir` to `results/.../clients/glog_t<tid>_c<cid>/` so glog and `LOG(INFO) metrics_summary` are on disk next to the run.
- `run_smoke.py` `parse_zmq_metrics` scans:
  - `workers/worker-<port>/*` (unchanged)
  - `clients/glog_*/*.INFO.log` and `*.INFO` (not `client_t*c*.log` stdout; those files can be huge and lack JSON).
- `collect_and_summarize` also copies `clients/glog_*` into the flat result dir for archiving.

## Histogram JSON gate (C++)

`BuildSummary` includes a histogram only when `slot.sum > 0`. `Observe(0)` increments count but not sum, so an all-zero histogram is omitted. Server reply also skips `Observe` when computed reply latency is 0 (`RecordServerReplyLatency`).

## 2026-04-25 remote outcome (regression)

- **Host:** `xqyun-32c32g`
- **Smoke (minimal for iteration):**  
  `python3 yuanrong-datasystem-agent-workbench/scripts/testing/verify/smoke/run_smoke.py --workers 1 --tenants 1 --clients-per-tenant 1`
- **Result (example run):** `results/smoke_test_20260425_154547/`
- **Checklist:** all 7 flow metrics `PASS` when `metrics_summary` JSON (worker) is combined with **diag** evidence in glog: `[ZmqRpcMetricsDiag] unary_RecordRpcLatencyMetrics … observe: queuing=1…` (client) and `[ZmqTickOrder] service_to_client_after_server_send` with `SERVER_DEQUEUE@`→`SERVER_SEND@` (worker), plus `[ZmqServerReplyDiag] reply_latency_ns=…` when the value is non-zero.
- **Notable:** `metrics_summary` in **client** `ds_client_*.INFO.log` was often **absent** (0 lines containing `event`); `InitKvMetrics` did not log an error, so a likely static-registry / ODR or logging path issue remains for future work. The smoke script no longer depends on client **JSON** alone.
- **C++ churn for this pass:** `metrics.cpp` histograms emit when `count>0` (not only `sum>0`); `zmq_service.cpp` adds `LOG` `[ZmqServerReplyDiag] …` for `reply_latency_ns` / `server_exec_end_ts` / `ticks=…`; `kv_client.cpp` applies `DATASYSTEM_SMOKE_CLIENT_LOG_MONITOR=1` and fails loudly if `InitKvMetrics` does not return OK.

## Remote verification (when available)

On `xqyun-32c32g` (or local), from the workbench repo:

```bash
export DS_OPENSOURCE_DIR="${DS_OPENSOURCE_DIR:-$HOME/.cache/yuanrong-datasystem-third-party}"
mkdir -p "$DS_OPENSOURCE_DIR" "${LOG_DIR:-$PWD/results}/smoke_manual"
python3 yuanrong-datasystem-agent-workbench/scripts/testing/verify/smoke/run_smoke.py
# Inspect: results/smoke_test_*/metrics_summary.txt
#         results/smoke_test_*/clients/glog_*/  (glog)
```

Reinstall the Python wheel on the run host if C++ ZMQ / metrics code changed.
