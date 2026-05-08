#!/usr/bin/env python3
"""
从 zmq_rpc_queue_latency_repl.log 中提取关键信息并美化输出。

metrics_summary 中 Histogram 使用每条 metric 的 total（不用 delta）：count / avg_us / max_us，
以及 p50、p90、p99（与 avg 同为微秒）。

用法:
    ./parse_repl_log.py <logfile>

示例:
    ./parse_repl_log.py results/zmq_rpc_queue_latency_repl.log
"""

import sys
import json
import re

def _parse_json_balance(content: str, brace_start: int) -> dict | None:
    depth = 0
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                json_str = content[brace_start : i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    return None
    return None


def extract_json_metrics(content: str) -> dict | None:
    """
    从日志内容中提取 metrics_summary JSON（支持 multi-part 分片）。

    日志格式为多行打印，每个 part_index 包含部分 metrics：
      {"event":"metrics_summary",...,"part_index":1,"part_count":4,...}
      {"event":"metrics_summary",...,"part_index":2,"part_count":4,...}
      ...
      === METRICS DUMP ===
      { 完整合并的 metrics_summary }

    解析策略：
    1. 优先找 "=== METRICS DUMP ===" 后的完整 JSON（已合并）
    2. 否则收集所有 part_index JSON，合并所有 metrics 数组
    """
    dump_marker = "=== METRICS DUMP ==="
    dm = content.find(dump_marker)
    if dm >= 0:
        brace_start = content.find("{", dm + len(dump_marker))
        if brace_start >= 0:
            full = _parse_json_balance(content, brace_start)
            if full and "metrics" in full:
                return full

    # Fallback: collect all part JSONs and merge metrics
    marker = '"event": "metrics_summary"'
    all_metrics = []
    pos = 0
    while True:
        idx = content.find(marker, pos)
        if idx < 0:
            break
        brace_start = content.rfind("{", 0, idx)
        if brace_start < 0:
            pos = idx + len(marker)
            continue
        part = _parse_json_balance(content, brace_start)
        if part and "metrics" in part:
            all_metrics.extend(part["metrics"])
        pos = idx + len(marker)

    if not all_metrics:
        return None
    return {"metrics": all_metrics}


def extract_rpc_summary(content: str) -> tuple[str, str, str]:
    """提取 'Completed N RPCs in Xms (Y req/s)' 行。"""
    match = re.search(r"Completed (\d+) RPCs in (\d+)ms \(([0-9.]+) req/s\)", content)
    if not match:
        return "", "", ""
    return match.group(1), match.group(2), match.group(3)


def format_hist_total(total: dict) -> str:
    """
    Render histogram stats from metric['total'] only (not delta).
    Fields are microseconds: avg_us, max_us; percentiles p50/p90/p99 when present.
    """
    cnt = total.get("count", 0)
    if cnt <= 0:
        return ""

    avg = total.get("avg_us", 0)
    mx = total.get("max_us", 0)
    parts = [f"count={cnt:,}", f"avg={avg:.1f}us", f"max={mx:.1f}us"]

    pct_parts = []
    for key in ("p50", "p90", "p99"):
        if key not in total or total[key] is None:
            continue
        try:
            pct_parts.append(f"{key}={int(total[key])}us")
        except (ValueError, TypeError):
            pct_parts.append(f"{key}={total[key]}")
    if pct_parts:
        parts.append(" ".join(pct_parts))

    return "  ".join(parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: parse_repl_log.py <logfile>")
        sys.exit(1)

    logfile = sys.argv[1]
    try:
        content = open(logfile).read()
    except FileNotFoundError:
        print(f"File not found: {logfile}")
        sys.exit(1)

    # 1. RPC 统计
    rpc_count, elapsed_ms, req_s = extract_rpc_summary(content)
    print("=" * 60)
    print("  ZMQ RPC Queue Latency — REPL Results")
    print("=" * 60)
    if rpc_count:
        print(f"  RPCs      : {int(rpc_count):,}")
        print(f"  Duration  : {int(elapsed_ms):,}ms")
        print(f"  QPS       : {float(req_s):.1f} req/s")
    else:
        print("  [No RPC summary found in log]")
    print()

    # 2. Metrics JSON
    data = extract_json_metrics(content)

    if not data or "metrics" not in data:
        print("  [No METRICS DUMP found in log]")
        return

    metrics_map = {m["name"]: m for m in data["metrics"]}

    print(f"  Interval  : {data.get('interval_ms', '?')}ms")
    print()

    # 2a. Queue-flow latency（Histogram：summary JSON 中为微秒 avg_us/max_us、p50/p90/p99）
    queue_flow_names = [
        # client-side
        "zmq_client_req_queuing_latency",
        "zmq_client_rsp_queuing_latency",
        # server-side
        "zmq_server_task_delay",
        "zmq_server_req_queuing_latency",
        "zmq_server_rsp_queuing_latency",
        "zmq_server_exec_latency",
        "zmq_server_poll_handle_latency",
        # e2e / network
        "zmq_rpc_e2e_latency",
        "zmq_rpc_network_latency",
    ]
    print("  ── Queue-Flow Latency (total / us) ────────────────────────")
    found_any_qf = False
    for name in queue_flow_names:
        m = metrics_map.get(name)
        display_name = name.replace("zmq_", "").replace("_latency", "")
        if m is None:
            print(f"    {display_name:30s}  {color('MISSING', 31)}")
        else:
            total = m.get("total") or {}
            if not isinstance(total, dict):
                print(f"    {display_name:30s}  {color('BAD total shape', 31)}")
                continue
            cnt = total.get("count", 0)
            if cnt > 0:
                line = format_hist_total(total)
                print(f"    {display_name:30s}  {line}")
                found_any_qf = True
            else:
                print(f"    {display_name:30s} count={cnt:>8,}  {color('MISSING', 31)}")
    if not found_any_qf:
        print(f"    {color('  ⚠ All queue-flow metrics have count=0 — tick recording may be broken', 33)}")
    print()

    # 2b. I/O & ser/deser
    print("  ── I/O & Serialization (total / us) ───────────────────────")
    for name in ["zmq_send_io_latency", "zmq_receive_io_latency",
                 "zmq_rpc_serialize_latency", "zmq_rpc_deserialize_latency"]:
        if name not in metrics_map:
            continue
        m = metrics_map[name]
        total = m.get("total") or {}
        if not isinstance(total, dict):
            continue
        display_name = name.replace("zmq_", "").replace("_latency", "")
        if total.get("count", 0) > 0:
            print(f"    {display_name:30s}  {format_hist_total(total)}")
        else:
            print(f"    {display_name:30s}  count=0  {color('MISSING', 31)}")
    print()

    # 2c. Fault counters
    print("  ── Fault Counters ──────────────────────────────────────────")
    counters_ok = True
    for name in ["zmq_send_failure_total", "zmq_receive_failure_total",
                 "zmq_network_error_total", "zmq_gateway_recreate_total"]:
        if name not in metrics_map:
            continue
        m = metrics_map[name]
        val = m.get("total", 0)
        display_name = name.replace("zmq_", "").replace("_total", "")
        if val == 0:
            print(f"    {display_name:30s} {color('OK', 32)} (0)")
        else:
            print(f"    {display_name:30s} {color('FAIL', 31)} ({val})")
            counters_ok = False
    if counters_ok:
        print("    (all zero)")
    print()
    print("=" * 60)


def color(text: str, code: int) -> str:
    return f"\033[{code}m{text}\033[0m"


if __name__ == "__main__":
    main()
