#!/usr/bin/env python3
"""
从 zmq_rpc_queue_latency_repl.log 中提取关键信息并美化输出。

用法:
    ./parse_repl_log.py <logfile>

示例:
    ./parse_repl_log.py results/zmq_rpc_queue_latency_repl.log
"""

import sys
import json
import re

EXPECTED_METRICS = [
    # Queue-flow latency (the ones we care about debugging)
    "zmq_client_queuing_latency",
    "zmq_client_stub_send_latency",
    "zmq_server_queue_wait_latency",
    "zmq_server_exec_latency",
    "zmq_server_reply_latency",
    "zmq_rpc_e2e_latency",
    "zmq_rpc_network_latency",
    # I/O metrics (these always work)
    "zmq_send_io_latency",
    "zmq_receive_io_latency",
    "zmq_rpc_serialize_latency",
    "zmq_rpc_deserialize_latency",
    # Fault counters
    "zmq_send_failure_total",
    "zmq_receive_failure_total",
    "zmq_network_error_total",
    "zmq_gateway_recreate_total",
]


def extract_json_metrics(content: str) -> dict | None:
    """从日志内容中提取 metrics_summary JSON（bazel --logtostderr 输出混有 protobuf 文本，需定位 "event": "metrics_summary" 块）。"""
    marker = '"event": "metrics_summary"'
    idx = content.find(marker)
    if idx < 0:
        return None

    # Backward find the opening brace of this JSON object
    brace_start = content.rfind("{", 0, idx)
    if brace_start < 0:
        return None

    # Find matching closing brace
    depth = 0
    for i in range(brace_start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                json_str = content[brace_start:i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    return None
    return None


def extract_rpc_summary(content: str) -> tuple[str, str, str]:
    """提取 'Completed N RPCs in Xms (Y req/s)' 行。"""
    match = re.search(r"Completed (\d+) RPCs in (\d+)ms \(([0-9.]+) req/s\)", content)
    if not match:
        return "", "", ""
    return match.group(1), match.group(2), match.group(3)


def format_us(value, unit="us"):
    """格式化 latency 值，ns -> us 自动转换。"""
    try:
        v = int(value)
        if v >= 1000:
            return f"{v / 1000:.1f}ms"
        return f"{v}{unit}"
    except (ValueError, TypeError):
        return str(value)


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

    # 2a. Queue-flow latency (ns unit metrics)
    queue_flow_names = [
        "zmq_client_queuing_latency",
        "zmq_client_stub_send_latency",
        "zmq_server_queue_wait_latency",
        "zmq_server_exec_latency",
        "zmq_server_reply_latency",
        "zmq_rpc_e2e_latency",
        "zmq_rpc_network_latency",
    ]
    print("  ── Queue-Flow Latency (ns) ────────────────────────────────")
    found_any_qf = False
    for name in queue_flow_names:
        m = metrics_map.get(name)
        display_name = name.replace("zmq_", "").replace("_latency", "")
        if m is None:
            print(f"    {display_name:30s}  {color('MISSING', 31)}")
        else:
            total = m.get("total", {})
            cnt = total.get("count", 0)
            avg = total.get("avg_us", 0)  # json 里存的是 us
            mx = total.get("max_us", 0)
            if cnt > 0:
                print(f"    {display_name:30s} count={cnt:>8,}  avg={avg:>8.1f}us  max={mx:>8.1f}us")
                found_any_qf = True
            else:
                print(f"    {display_name:30s} count={cnt:>8,}  {color('MISSING', 31)}")
    if not found_any_qf:
        print(f"    {color('  ⚠ All queue-flow metrics have count=0 — tick recording may be broken', 33)}")
    print()

    # 2b. I/O & ser/deser
    print("  ── I/O & Serialization ─────────────────────────────────────")
    for name in ["zmq_send_io_latency", "zmq_receive_io_latency",
                 "zmq_rpc_serialize_latency", "zmq_rpc_deserialize_latency"]:
        if name not in metrics_map:
            continue
        m = metrics_map[name]
        total = m.get("total", {})
        cnt = total.get("count", 0)
        avg = total.get("avg_us", 0)
        mx = total.get("max_us", 0)
        display_name = name.replace("zmq_", "").replace("_latency", "")
        print(f"    {display_name:30s} count={cnt:>8,}  avg={avg:>8.1f}us  max={mx:>8.1f}us")
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
