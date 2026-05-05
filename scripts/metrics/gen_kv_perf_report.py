#!/usr/bin/env python3
# Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.
"""
从 glog / 文本中提取 metrics_summary（及可选 Perf Log、压测摘要），生成与手工 breakdown 对齐的 Markdown 报告。

分析语义（与 docs 中「Client / Worker1 / Worker2 / URMA」段落一致）:
  - client_rpc_get_latency     → 客户端视角 RPC 耗时（Histogram，微秒）
  - worker_process_get_latency → 入口 worker 上 Get 处理（MsgQ 下为排队+执行，微秒）
  - worker_rpc_query_meta_latency → 查 meta / master 路径（微秒）
  - worker_rpc_get_remote_object_latency 或 worker_rpc_remote_get_outbound_latency → 跨 worker pull（微秒）
  - worker_urma_write_latency / worker_urma_wait_latency → 对端数据面（微秒）
  （ZMQ 分段延迟 metrics 采集不可靠，本报告不包含 zmq_* 直方图。）

用法:
  python3 gen_kv_perf_report.py worker.INFO.log [client.INFO.log ...]
  python3 gen_kv_perf_report.py --bench-stats bench.txt yche.log
  python3 gen_kv_perf_report.py --last-only false *.log   # 输出每个 metrics_summary 一行表

  cat yche.log | python3 gen_kv_perf_report.py -

  python3 gen_kv_perf_report.py --ascii-tree worker.INFO.log   # 两层 ASCII 树（关键 + 细化）

  python3 gen_kv_perf_report.py -o output.log logs/input.log  # 写入文件（管道/自定义前缀 metrics 行亦支持）

  python3 gen_kv_perf_report.py --dual-out logs/metrics   # metrics_total.log / metrics_delta.log / metrics.json（pretty）
  python3 gen_kv_perf_report.py --dual-out                # output_total.log / output_delta.log / output.json

bench-stats 文件示例（冒号或等号分隔，# 开头为注释）:
  Total: 40976
  Success: 40976
  Avg_ms: 3.612
  P99_ms: 8.433
  QPS: 303.526
  Throughput_MBs: 1291.49
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from json import JSONDecoder
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

HistBucket = Literal["total", "delta"]

# 多行 metrics_summary 时，delta 报告按 delta.count 选「负载最大」的快照（优先 Get 主路径）
_DELTA_SCORE_PREFERRED_KEYS: Tuple[str, ...] = (
    "worker_process_get_latency",
    "zmq_rpc_e2e_latency",
    "client_rpc_get_latency",
)

# ---------------------------------------------------------------------------
# 报告章节： (标题, [(metric_name, 一行说明)])
# ---------------------------------------------------------------------------
REPORT_SECTIONS: List[Tuple[str, List[Tuple[str, str]]]] = [
    (
        "Client → Worker（客户端 / 压测进程）",
        [
            ("client_rpc_get_latency", "`client_rpc_get_latency`：client 侧 get RPC 直方图（**µs**）"),
        ],
    ),
    (
        "入口 Worker 处理",
        [
            (
                "worker_process_get_latency",
                "`worker_process_get_latency`：Get 在 worker 上处理（MsgQ 时常为排队+执行，**µs**）",
            ),
            (
                "worker_get_threadpool_queue_latency",
                "`worker_get_threadpool_queue_latency`：线程池排队（**µs**，仅 MsgQ）",
            ),
            (
                "worker_get_threadpool_exec_latency",
                "`worker_get_threadpool_exec_latency`：`ProcessGetObjectRequest` 执行（**µs**）",
            ),
        ],
    ),
    (
        "Worker ↔ Worker / Meta（跨节点与查 meta）",
        [
            (
                "worker_rpc_query_meta_latency",
                "`worker_rpc_query_meta_latency`：query meta 路径（**µs**）；常对应「W1→meta/下一跳」量级参考",
            ),
            (
                "worker_rpc_get_remote_object_latency",
                "`worker_rpc_get_remote_object_latency`：跨 worker 拉对象（**µs**，旧名/日志名）",
            ),
            (
                "worker_rpc_remote_get_outbound_latency",
                "`worker_rpc_remote_get_outbound_latency`：出站 remote get（**µs**，与上一项二选一）",
            ),
            (
                "worker_rpc_remote_get_inbound_latency",
                "`worker_rpc_remote_get_inbound_latency`：对端入站 remote get（**µs**）",
            ),
            (
                "worker_get_meta_addr_hashring_latency",
                "`worker_get_meta_addr_hashring_latency`：hash ring 选址（**µs**）",
            ),
            (
                "worker_get_post_query_meta_phase_latency",
                "`worker_get_post_query_meta_phase_latency`：query meta 之后阶段（**µs**）",
            ),
        ],
    ),
    (
        "数据面（URMA）",
        [
            ("worker_urma_write_latency", "`worker_urma_write_latency`：**µs**"),
            ("worker_urma_wait_latency", "`worker_urma_wait_latency`：**µs**"),
            ("urma_import_jfr", "`urma_import_jfr`：**µs**"),
        ],
    ),
]

# Perf 行: KEY: {json}
PERF_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*:\s*(\{.*\})\s*$")

# perf_manager 聚合块标记（块内多行 KEY: {...}）
PERF_LOG_MARKER = "[Perf Log]:"

# 图 1 末尾：与 metrics 关键路径对照的 Perf 锚点（存在则打印）
ASCII_PERF_CRITICAL_KEYS: List[str] = [
    "WORKER_GET_OBJECT",
    "WORKER_PROCESS_GET_OBJECT",
    "WORKER_QUERY_META",
    "WORKER_BATCH_REMOTE_GET_RPC",
    "WORKER_PULL_REMOTE_DATA",
    "FAST_TRANSPORT_TOTAL_EVENT_WAIT",
    "URMA_WAIT_TIME",
    "URMA_WRITE_TOTAL",
]

# 图 2：按调用语义分组的 Perf 细项（仅输出日志中存在的 key）
ASCII_PERF_DETAIL_SECTIONS: List[Tuple[str, List[str]]] = [
    (
        "[Perf] Create / Seal / Meta / 内存",
        [
            "WORKER_CREATE_OBJECT",
            "WORKER_SEAL_OBJECT",
            "WORKER_CREATE_META",
            "WORKER_MEMORY_ALLOCATE",
            "WORKER_CLEAR_OBJECT",
        ],
    ),
    (
        "[Perf] Get — 批处理骨架",
        [
            "WORKER_GET_REQUEST_INIT",
            "WORKER_GET_BATCH_BEFORE_RUN",
            "WORKER_GET_BATCH_RUN",
            "WORKER_GET_BATCH_AFTER_RUN",
            "WORKER_GET_BATCH_GROUPBY_DATA_NODE",
            "WORKER_GET_BATCH_HANDLE_DATA_IN_META",
            "WORKER_GET_BATCH_OTHER",
        ],
    ),
    (
        "[Perf] Get — query_meta 细分",
        [
            "WORKER_QUERY_META",
            "WORKER_QUERY_META_PRE",
            "WORKER_QUERY_META_ROUTER",
            "WORKER_QUERY_META_BATCH_BY_ADDR",
            "WORKER_QUERY_META_HANDLE_NOT_FOUND",
            "WORKER_QUERY_META_HANDLE_RESULT",
            "WORKER_QUERY_META_OTHER",
        ],
    ),
    (
        "[Perf] Get — batch 构造与 RPC",
        [
            "WORKER_CONSTRUCT_BATCH_GET_REQ",
            "WORKER_BATCH_GET_CONSTRUCT_AND_SEND_PRE",
            "WORKER_BATCH_GET_CONSTRUCT_GET_REQUEST",
            "WORKER_BATCH_GET_CREATE_REMOTE_API",
            "WORKER_BATCH_GET_SEND_AND_RECV",
            "WORKER_BATCH_REMOTE_GET_RPC",
            "WORKER_BATCH_GET_CONSTRUCT_AND_SEND",
            "WORKER_BATCH_GET_HANDLE_RESPONSE",
        ],
    ),
    (
        "[Perf] Get — 对端 server / payload",
        [
            "WORKER_SERVER_GET_REMOTE",
            "WORKER_SERVER_GET_REMOTE_IMPL",
            "WORKER_SERVER_GET_REMOTE_READ",
            "WORKER_SERVER_BATCH_GET_REMOTE",
            "WORKER_SERVER_GET_REMOTE_WRITE",
            "WORKER_SERVER_GET_REMOTE_SENDPAYLOAD",
            "WORKER_REMOTE_GET_PAYLOAD",
            "WORKER_REMOTE_GET_PAYLOAD_SHM_UNIT",
            "WORKER_REMOTE_GET_READ_KEY",
            "WORKER_LOAD_OBJECT_DATA",
        ],
    ),
    (
        "[Perf] Get — 远端路径汇总",
        [
            "WORKER_PROCESS_GET_FROM_REMOTE",
            "WORKER_PROCESS_GET_OBJECT_REMOTE",
            "WORKER_PULL_REMOTE_DATA",
        ],
    ),
    (
        "[Perf] 回包 / 本地 Get",
        [
            "WORKER_RETURN_TO_CLIENT_PRE",
            "WORKER_RETURN_TO_CLIENT_CONSTRUCT_RESPONSE",
            "WORKER_RETURN_TO_CLIENT_OTHER",
            "WORKER_PROCESS_GET_FROM_LOCAL",
            "WORKER_PROCESS_GET_FROM_LOCAL_BATCH",
        ],
    ),
    (
        "[Perf] URMA 细项",
        [
            "URMA_WRITE_TOTAL",
            "URMA_WRITE_FIND_CONNECTION",
            "URMA_WRITE_FIND_REMOTE_SEGMENT",
            "URMA_WRITE_REGISTER_LOCAL_SEGMENT",
            "URMA_WRITE_LOOP",
            "URMA_WRITE_SINGLE",
            "FAST_TRANSPORT_TOTAL_EVENT_WAIT",
            "URMA_WAIT_TO_FINISH",
            "URMA_WAIT_TIME",
            "URMA_IMPORT_JFR",
            "URMA_IMPORT_REMOTE_SEGMENT",
        ],
    ),
    (
        "[Perf] ZMQ（tick 垃圾项已跳过）",
        [
            "ZMQ_APP_WORKLOAD",
            "ZMQ_FRONTEND_TO_WORKER",
            "ZMQ_BACKEND_TO_FRONTEND",
            "ZMQ_ROUTER_TO_SVC",
            "ZMQ_STUB_FRONT_TO_BACK",
            "ZMQ_STUB_BACK_TO_FRONT",
            "ZMQ_STUB_ROUTE_MSG",
            "ZMQ_QUERYMETA_RPC",
            "ZMQ_CREATEMETA_RPC",
            "ZMQ_ADAPTOR_LAYER_QUERYMETA",
            "ZMQ_ADAPTOR_LAYER_CREATEMETA",
            "ZMQ_COM_SERIAL_TO_ZMQ_MESSAGE",
            "ZMQ_SOCKET_GET_ALL_MSG",
            "ZMQ_SOCKET_SEND_MSG",
        ],
    ),
    (
        "[Perf] Master",
        [
            "MASTER_QUERY_META",
            "MASTER_CREATE_META",
            "MASTER_QUERY_META_FROM_META_TABLE",
            "MASTER_QUERY_META_FILL_REDIRECT",
            "MASTER_SELECT_LOCATION",
        ],
    ),
    (
        "[Perf] 分配 / jemalloc",
        [
            "JEMALLOC_ALLOCATE_SUCCESS",
            "JEMALLOC_FREE",
            "ALLOCATE_GET_MAP",
            "ALLOCATE_FREE_WAIT_LOCK",
            "ALLOCATE_FREE_HOLD_LOCK",
        ],
    ),
]

# metrics_summary 在行内 JSON 起始（兼容 glog、管道分隔一行一条等前缀）
METRICS_SUMMARY_JSON_START_RE = re.compile(
    r'\{\s*"event"\s*:\s*"metrics_summary"'
)

# kv_metrics 中 Observe 为纳秒、JSON 仍写 avg_us/max_us 的直方图
ZMQ_HISTOGRAM_NS = frozenset(
    {
        "zmq_client_queuing_latency",
        "zmq_server_queue_wait_latency",
        "zmq_server_exec_latency",
        "zmq_server_reply_latency",
        "zmq_rpc_e2e_latency",
        "zmq_rpc_network_latency",
    }
)


@dataclass
class MetricsSnapshot:
    source_line_hint: str = ""
    cycle: Optional[int] = None
    interval_ms: Optional[int] = None
    part_index: Optional[int] = None
    part_count: Optional[int] = None
    by_name: Dict[str, Any] = field(default_factory=dict)


def _extract_json_object(line: str, start: int) -> Optional[Tuple[Any, int]]:
    dec = JSONDecoder()
    try:
        obj, end = dec.raw_decode(line, start)
        return obj, end
    except json.JSONDecodeError:
        return None


def iter_metrics_summary_objects(path: str) -> Iterable[Tuple[str, dict]]:
    """Yield (source_hint, parsed_json) for each metrics_summary object in file or stdin."""
    if path == "-":
        lines = sys.stdin
        hint_prefix = "stdin"
    else:
        lines = open(path, "r", encoding="utf-8", errors="replace")
        hint_prefix = path

    for lineno, line in enumerate(lines, 1):
        for m in METRICS_SUMMARY_JSON_START_RE.finditer(line):
            got = _extract_json_object(line, m.start())
            if got and got[0].get("event") == "metrics_summary":
                yield (f"{hint_prefix}:{lineno}", got[0])

    if path != "-":
        lines.close()


def snapshot_from_obj(source_hint: str, obj: dict) -> MetricsSnapshot:
    snap = MetricsSnapshot(
        source_line_hint=source_hint,
        cycle=obj.get("cycle"),
        interval_ms=obj.get("interval_ms"),
        part_index=obj.get("part_index"),
        part_count=obj.get("part_count"),
    )
    for item in obj.get("metrics") or []:
        name = item.get("name")
        if name:
            snap.by_name[name] = item
    return snap


def _snap_line_for_tie(snap: MetricsSnapshot) -> int:
    _, ln = parse_source_hint(snap.source_line_hint)
    return int(ln) if ln is not None else 0


def _delta_snapshot_score(snap: MetricsSnapshot) -> int:
    """用于多行输入时选「delta 负载」最大的一行：优先主路径直方图 delta.count，否则取全体直方图 delta.count 最大。"""
    bn = snap.by_name
    for k in _DELTA_SCORE_PREFERRED_KEYS:
        it = bn.get(k)
        if not it or not isinstance(it, dict):
            continue
        d = it.get("delta")
        if isinstance(d, dict) and isinstance(d.get("count"), int):
            c = int(d["count"])
            if c > 0:
                return c
    best = 0
    for it in bn.values():
        if not isinstance(it, dict):
            continue
        d = it.get("delta")
        if isinstance(d, dict) and isinstance(d.get("count"), int):
            best = max(best, int(d["count"]))
    return best


def collect_summary_pairs(paths: List[str], last_only: bool) -> List[Tuple[str, dict]]:
    """与 collect_snapshots_for_paths 选帧规则一致，返回 (source_hint, metrics_summary 对象原文)。"""
    out: List[Tuple[str, dict]] = []
    for path in paths:
        last_pair: Optional[Tuple[str, dict]] = None
        for hint, obj in iter_metrics_summary_objects(path):
            if last_only:
                last_pair = (hint, obj)
            else:
                out.append((hint, obj))
        if last_only and last_pair is not None:
            out.append(last_pair)
    return out


def summary_pairs_max_delta_per_path(paths: List[str]) -> List[Tuple[str, dict]]:
    """与 snapshots_max_delta_per_path 一致：每文件选一帧（delta 负载最大）。"""
    picked: List[Tuple[str, dict]] = []
    for path in paths:
        pairs = list(iter_metrics_summary_objects(path))
        if not pairs:
            continue
        best = max(
            pairs,
            key=lambda ho: (
                _delta_snapshot_score(snapshot_from_obj(ho[0], ho[1])),
                _snap_line_for_tie(snapshot_from_obj(ho[0], ho[1])),
            ),
        )
        picked.append(best)
    return picked


def collect_snapshots_for_paths(paths: List[str], last_only: bool) -> List[MetricsSnapshot]:
    """与历史 main 一致：每文件 last_only 时只保留最后一帧，否则保留全部（按文件顺序拼接）。"""
    return [snapshot_from_obj(h, o) for h, o in collect_summary_pairs(paths, last_only)]


def snapshots_max_delta_per_path(paths: List[str]) -> List[MetricsSnapshot]:
    """每文件独立：在全部 metrics_summary 行中选 delta 负载最大的一帧（同分取行号较大者）。"""
    return [snapshot_from_obj(h, o) for h, o in summary_pairs_max_delta_per_path(paths)]


def format_histogram_total(item: dict, *, bucket: HistBucket = "total") -> str:
    t = item.get(bucket)
    if isinstance(t, dict):
        return json.dumps(t, ensure_ascii=False, separators=(",", ":"))
    if bucket == "delta":
        return "{}"
    t0 = item.get("total")
    if isinstance(t0, dict):
        return json.dumps(t0, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(item, ensure_ascii=False, separators=(",", ":"))


def _hist_parts(
    by_name: Dict[str, Any], key: str, *, bucket: HistBucket = "total"
) -> Optional[Tuple[int, int, int]]:
    it = by_name.get(key)
    if not it:
        return None
    t = it.get(bucket)
    if not isinstance(t, dict) or "count" not in t:
        return None
    c = t.get("count")
    a = t.get("avg_us")
    m = t.get("max_us")
    if not isinstance(c, int) or not isinstance(a, (int, float)) or not isinstance(m, (int, float)):
        return None
    return int(c), int(a), int(m)


def _fmt_hist_line(
    key: str,
    by_name: Dict[str, Any],
    *,
    ns: bool = False,
    bucket: HistBucket = "total",
) -> Optional[str]:
    p = _hist_parts(by_name, key, bucket=bucket)
    if not p:
        return None
    c, a, m = p
    unit = "ns" if ns else "µs"
    return f"{key}  n={c}  avg={a}{unit}  max={m}{unit}"


def _fmt_scalar_line(
    key: str, by_name: Dict[str, Any], *, bucket: HistBucket = "total"
) -> Optional[str]:
    it = by_name.get(key)
    if not it:
        return None
    tot = it.get("total")
    d = it.get("delta", 0)
    if isinstance(tot, (int, float)):
        if bucket == "delta":
            return f"{key}  delta={d}  total_now={tot}"
        return f"{key}  total={tot}  delta={d}"
    return None


def _emit_subtree(title: str, lines_out: List[str], children: List[Optional[str]]) -> None:
    lines_out.append(title)
    valid = [c for c in children if c]
    if not valid:
        lines_out.append("└── (本快照无此项)")
        return
    for i, c in enumerate(valid):
        prefix = "└── " if i == len(valid) - 1 else "├── "
        lines_out.append(prefix + c)


def parse_source_hint(source_hint: str) -> Tuple[str, Optional[int]]:
    if ":" not in source_hint:
        return source_hint, None
    path, _, line_s = source_hint.rpartition(":")
    try:
        return path, int(line_s)
    except ValueError:
        return source_hint, None


def _perf_tick_garbage(js: dict) -> bool:
    avg = js.get("avgTime")
    mx = js.get("maxTime")
    if isinstance(avg, (int, float)) and avg > 10**15:
        return True
    if isinstance(mx, (int, float)) and mx > 10**18:
        return True
    return False


def _fmt_perf_line(key: str, perf_map: Dict[str, dict]) -> Optional[str]:
    js = perf_map.get(key)
    if not js:
        return None
    if _perf_tick_garbage(js):
        return f"{key}  (跳过: avg/max 异常，tick 不可靠)"
    cnt = js.get("count")
    avg = js.get("avgTime")
    mx = js.get("maxTime")
    if not isinstance(cnt, int) or not isinstance(avg, (int, float)) or not isinstance(
        mx, (int, float)
    ):
        return None
    avg_us = float(avg) / 1000.0
    mx_us = float(mx) / 1000.0
    return f"{key}  n={cnt}  avg={avg_us:.1f}µs  max={mx_us:.1f}µs"


def extract_perf_map_near_metrics(path: str, metrics_lineno: int) -> Dict[str, dict]:
    """从 metrics_summary 所在行附近解析最近一次 [Perf Log]: 块为 key -> json。"""
    if path in ("-", "stdin") or metrics_lineno < 1:
        return {}
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return {}
    idx0 = metrics_lineno - 1
    if idx0 < 0 or idx0 >= len(lines):
        return {}

    header_idx: Optional[int] = None
    max_scan = 8000
    for i in range(idx0, min(len(lines), idx0 + max_scan)):
        if PERF_LOG_MARKER in lines[i]:
            header_idx = i
            break
    if header_idx is None:
        for i in range(idx0 - 1, max(-1, idx0 - max_scan), -1):
            if PERF_LOG_MARKER in lines[i]:
                header_idx = i
                break
    if header_idx is None:
        return {}

    out: Dict[str, dict] = {}
    for j in range(header_idx + 1, len(lines)):
        raw = lines[j].strip()
        if not raw:
            continue
        if raw.startswith("#"):
            break
        m = PERF_LINE_RE.match(raw)
        if not m:
            if "|" in raw and ("INFO" in raw or " I |" in raw) and "metrics_summary" not in raw:
                break
            break
        try:
            out[m.group(1)] = json.loads(m.group(2))
        except json.JSONDecodeError:
            continue
    return out


def _perf_map_for_snapshot(snap: MetricsSnapshot) -> Dict[str, dict]:
    path, lineno = parse_source_hint(snap.source_line_hint)
    if lineno is None:
        return {}
    return extract_perf_map_near_metrics(path, lineno)


def _emit_perf_section(
    title: str, lines_out: List[str], keys: List[str], perf_map: Dict[str, dict]
) -> None:
    children: List[Optional[str]] = [_fmt_perf_line(k, perf_map) for k in keys]
    if not any(children):
        return
    _emit_subtree(title, lines_out, children)


def render_ascii_breakdown(
    snap: MetricsSnapshot, *, hist_bucket: HistBucket = "total"
) -> str:
    """两层 ASCII 树：图1 关键路径，图2 细化（含 PerfPoint、ZMQ/资源/Master 等）。"""
    bn = snap.by_name
    perf_map = _perf_map_for_snapshot(snap)
    out: List[str] = []

    out.append("=" * 76)
    out.append("图 1 — 关键路径 breakdown（直方图勿相加；嵌套/重复计入见代码树文档）")
    out.append("=" * 76)
    out.append(f"来源: {snap.source_line_hint}")
    out.append(
        f"cycle={snap.cycle}  interval_ms={snap.interval_ms}  "
        f"part={snap.part_index}/{snap.part_count}"
    )
    out.append("")

    _emit_subtree(
        "[Client]",
        out,
        [_fmt_hist_line("client_rpc_get_latency", bn, bucket=hist_bucket)],
    )
    out.append("")

    _emit_subtree(
        "[入口 Worker / 线程池]",
        out,
        [
            _fmt_hist_line("worker_process_get_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_get_threadpool_queue_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_get_threadpool_exec_latency", bn, bucket=hist_bucket),
        ],
    )
    out.append("")

    _emit_subtree(
        "[→ Master] 查 meta",
        out,
        [_fmt_hist_line("worker_rpc_query_meta_latency", bn, bucket=hist_bucket)],
    )
    out.append("")

    _emit_subtree(
        "[→ 对端 Worker] 拉对象（日志旧名/新名二选一）",
        out,
        [
            _fmt_hist_line("worker_rpc_get_remote_object_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_rpc_remote_get_outbound_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_rpc_remote_get_inbound_latency", bn, bucket=hist_bucket),
        ],
    )
    out.append("")

    _emit_subtree(
        "[URMA 数据面]",
        out,
        [
            _fmt_hist_line("worker_urma_write_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_urma_wait_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("urma_import_jfr", bn, bucket=hist_bucket),
        ],
    )
    out.append("")

    if not perf_map:
        out.append("[Perf] 关键路径锚点（PerfPoint，源数据为 ns）")
        out.append(
            "└── (同文件 metrics 行附近无 [Perf Log]；stdin 或未开 ENABLE_PERF 时为空)"
        )
    else:
        _emit_subtree(
            "[Perf] 关键路径锚点（PerfPoint；嵌套勿相加，勿与上列 metrics 混加）",
            out,
            [_fmt_perf_line(k, perf_map) for k in ASCII_PERF_CRITICAL_KEYS],
        )
    out.append("")

    out.append("=" * 76)
    out.append(
        "图 2 — 细化（PerfPoint 树、metrics Create/选址、ZMQ、资源与 Master）"
    )
    out.append("=" * 76)

    if not perf_map:
        out.append("[Perf] 细化树")
        out.append(
            "└── (无 Perf 块：仅含 metrics_summary 的日志不会出现 WORKER_* Perf 行)"
        )
        out.append("")
    else:
        out.append("[Perf] 细化树（与代码阶段大致对应；子项之和 ≠ 父项）")
        out.append("")
        for sec_title, sec_keys in ASCII_PERF_DETAIL_SECTIONS:
            _emit_perf_section(sec_title, out, sec_keys, perf_map)
            out.append("")

    _emit_subtree(
        "[Worker CRUD / RPC 耗时]",
        out,
        [
            _fmt_hist_line("worker_process_create_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_process_publish_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_rpc_create_meta_latency", bn, bucket=hist_bucket),
        ],
    )
    out.append("")

    _emit_subtree(
        "[Get 后段 / 选址]",
        out,
        [
            _fmt_hist_line("worker_get_meta_addr_hashring_latency", bn, bucket=hist_bucket),
            _fmt_hist_line("worker_get_post_query_meta_phase_latency", bn, bucket=hist_bucket),
        ],
    )
    out.append("")

    zmq_us = [
        _fmt_hist_line("zmq_send_io_latency", bn, bucket=hist_bucket),
        _fmt_hist_line("zmq_receive_io_latency", bn, bucket=hist_bucket),
        _fmt_hist_line("zmq_rpc_serialize_latency", bn, bucket=hist_bucket),
        _fmt_hist_line("zmq_rpc_deserialize_latency", bn, bucket=hist_bucket),
    ]
    _emit_subtree("[ZMQ] IO/序列化（µs，ScopedTimer）", out, zmq_us)
    out.append("")

    zmq_ns_lines: List[Optional[str]] = []
    for zk in sorted(ZMQ_HISTOGRAM_NS):
        line = _fmt_hist_line(zk, bn, ns=True, bucket=hist_bucket)
        if line and zk == "zmq_server_reply_latency":
            p = _hist_parts(bn, zk, bucket=hist_bucket)
            if p and p[2] > 10**15:
                line = f"{zk}  (跳过展示: max 异常大，tick 不可靠)"
        zmq_ns_lines.append(line)
    _emit_subtree("[ZMQ] 分段（Observe 为 ns，JSON 字段名仍为 avg_us/max_us）", out, zmq_ns_lines)
    out.append("")

    res_children = [
        _fmt_scalar_line("worker_object_count", bn, bucket=hist_bucket),
        _fmt_scalar_line("worker_allocated_memory_size", bn, bucket=hist_bucket),
        _fmt_scalar_line("worker_allocator_alloc_bytes_total", bn, bucket=hist_bucket),
        _fmt_scalar_line("worker_allocator_free_bytes_total", bn, bucket=hist_bucket),
        _fmt_scalar_line("worker_shm_unit_created_total", bn, bucket=hist_bucket),
        _fmt_scalar_line("worker_shm_unit_destroyed_total", bn, bucket=hist_bucket),
        _fmt_scalar_line("worker_object_erase_total", bn, bucket=hist_bucket),
    ]
    _emit_subtree("[资源 / SHM / 分配器]", out, res_children)
    out.append("")

    master_children = [
        _fmt_scalar_line("master_object_meta_table_size", bn, bucket=hist_bucket),
        _fmt_scalar_line("master_ttl_pending_size", bn, bucket=hist_bucket),
        _fmt_scalar_line("master_ttl_fire_total", bn, bucket=hist_bucket),
        _fmt_scalar_line("master_ttl_delete_success_total", bn, bucket=hist_bucket),
        _fmt_scalar_line("master_ttl_delete_failed_total", bn, bucket=hist_bucket),
    ]
    _emit_subtree("[Master 同进程指标]（若存在）", out, master_children)
    out.append("")

    return "\n".join(out)


def sanity_warnings(by_name: Dict[str, Any]) -> List[str]:
    """Reserved for future heuristics; ZMQ histograms are omitted from the report."""
    _ = by_name
    return []


def parse_bench_stats(path: str) -> Dict[str, str]:
    kv: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for sep in (":", "="):
                if sep in line:
                    k, v = line.split(sep, 1)
                    kv[k.strip()] = v.strip()
                    break
    return kv


def format_bench_section(stats: Dict[str, str]) -> str:
    if not stats:
        return ""
    lines = ["#### 压测工具采集（来自 --bench-stats）", ""]
    order = [
        ("Total", "Total"),
        ("Success", "Success"),
        ("Fail", "Fail"),
        ("Avg_ms", "Avg（ms）"),
        ("P90_ms", "P90（ms）"),
        ("P99_ms", "P99（ms）"),
        ("Min_ms", "Min（ms）"),
        ("Max_ms", "Max（ms）"),
        ("QPS", "QPS"),
        ("Throughput_MBs", "Throughput（MB/s）"),
    ]
    for key, label in order:
        if key in stats:
            lines.append(f"- **{label}**: {stats[key]}")
    for k, v in sorted(stats.items()):
        if k not in {x[0] for x in order}:
            lines.append(f"- **{k}**: {v}")
    lines.append("")
    return "\n".join(lines)


def iter_perf_lines(path: str) -> Iterable[Tuple[str, dict]]:
    if path == "-":
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = PERF_LINE_RE.match(line.rstrip())
            if not m:
                continue
            try:
                yield m.group(1), json.loads(m.group(2))
            except json.JSONDecodeError:
                continue


def format_perf_section(paths: List[str], keys_filter: Optional[List[str]] = None) -> str:
    """Optional compact perf table from logs (first file that has perf keys)."""
    want = set(keys_filter) if keys_filter else None
    rows: List[str] = []
    for p in paths:
        if p == "-":
            continue
        for key, js in iter_perf_lines(p):
            if want is not None and key not in want:
                continue
            avg_ns = js.get("avgTime")
            cnt = js.get("count")
            mx = js.get("maxTime")
            if cnt:
                rows.append(
                    f"| `{key}` | {cnt} | {avg_ns} | {mx} | "
                    f"avg {float(avg_ns) / 1000.0:.3f} µs |"
                )
        if rows:
            break
    if not rows:
        return ""
    header = (
        "| PerfKey | count | avgTime(ns) | maxTime(ns) | avg(µs) |\n"
        "|---------|------:|------------:|------------:|--------:|\n"
    )
    return (
        "#### Perf Log 摘录（**ns**；ENABLE_PERF 编译且日志含 `[Perf Log]` 时才有数据）\n\n"
        + header
        + "\n".join(rows)
        + "\n\n"
    )


def render_report(
    snap: MetricsSnapshot,
    bench_stats: Optional[Dict[str, str]] = None,
    perf_paths: Optional[List[str]] = None,
    perf_keys: Optional[List[str]] = None,
    *,
    hist_bucket: HistBucket = "total",
) -> str:
    parts: List[str] = []
    parts.append("### 性能 Breakdown 报告（自动生成）\n")
    parts.append(f"- **metrics 来源**: `{snap.source_line_hint}`\n")
    if hist_bucket == "delta":
        parts.append(
            "- **统计口径**: 直方图与各指标展示 **delta** 桶（本 interval 增量）；"
            "同一输入文件多行 `metrics_summary` 时，delta 报告 **按 delta 负载最大的一行**选取。\n"
        )
    else:
        parts.append("- **统计口径**: 直方图与各指标展示 **total** 桶（累计）。\n")
    if snap.cycle is not None:
        parts.append(
            f"- **cycle** / **interval_ms** / **part**: {snap.cycle} / "
            f"{snap.interval_ms} / {snap.part_index} of {snap.part_count}\n"
        )
    parts.append("\n")

    if bench_stats:
        parts.append(format_bench_section(bench_stats))

    parts.append("#### 与手工分析对齐的 Metrics 树\n")
    parts.append(
        "> 说明：下列 **非严格可加树**；跨 worker 与 client 并行时，不能期望子项之和等于 `client_rpc_get_latency`。\n\n"
    )

    for section_title, metrics in REPORT_SECTIONS:
        parts.append(f"##### {section_title}\n\n")
        any_m = False
        for mname, desc in metrics:
            item = snap.by_name.get(mname)
            if not item:
                continue
            any_m = True
            parts.append(f"- {desc}\n")
            parts.append(
                f"  - `{format_histogram_total(item, bucket=hist_bucket)}`\n"
            )
        if not any_m:
            parts.append("- *（本 snapshot 无此段指标）*\n")
        parts.append("\n")

    warns = sanity_warnings(snap.by_name)
    parts.append("#### 异常与健康检查\n\n")
    if warns:
        for w in warns:
            parts.append(f"- ⚠ {w}\n")
    else:
        parts.append("- （未触发其它启发式告警）\n")
    parts.append("\n")

    if perf_paths:
        perf_block = format_perf_section(perf_paths, perf_keys)
        if perf_block:
            parts.append(perf_block)

    parts.append(
        "#### 运维提示（可粘贴到报告尾部）\n\n"
        "- Poll-thread / Rpc-thread：`UrmaEventHandler` 相关日志可与 `worker_urma_wait_latency` 对照。\n"
        "- RPC 线程数 / 队列深度：结合 `worker_get_threadpool_queue_latency` 与线程池统计日志。\n"
    )
    return "".join(parts)


def render_table_row(
    source: str,
    snap: MetricsSnapshot,
    *,
    hist_bucket: HistBucket = "total",
) -> str:
    def avg(name: str) -> str:
        it = snap.by_name.get(name)
        if not it:
            return "-"
        t = it.get(hist_bucket)
        if isinstance(t, dict) and "avg_us" in t:
            return str(t["avg_us"])
        return "-"

    cols = [
        snap.cycle,
        avg("client_rpc_get_latency"),
        avg("worker_process_get_latency"),
        avg("worker_rpc_query_meta_latency"),
        avg("worker_rpc_get_remote_object_latency"),
        avg("worker_rpc_remote_get_outbound_latency"),
        avg("worker_urma_wait_latency"),
    ]
    return "| " + " | ".join(str(c) for c in cols) + f" | `{source}` |"


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_metrics_summary_json_bundle(
    out_path: str,
    *,
    pairs_total: List[Tuple[str, dict]],
    pairs_delta: List[Tuple[str, dict]],
    last_only_total: bool,
) -> None:
    """将 total / delta 选取对应的原始 metrics_summary 对象格式化写入单个 JSON。"""
    _ensure_parent_dir(out_path)
    payload: Dict[str, Any] = {
        "schema": "kv_perf_report_metrics_summary_v1",
        "total_selection": {"last_only": last_only_total},
        "delta_selection": {
            "rule": (
                "per_input_file_pick_row_with_max_histogram_delta_load"
            ),
            "preferred_keys_order": list(_DELTA_SCORE_PREFERRED_KEYS),
            "tie_break": "max_source_line_number",
        },
        "total": [{"source": s, "metrics_summary": dict(obj)} for s, obj in pairs_total],
        "delta_selected": [
            {"source": s, "metrics_summary": dict(obj)} for s, obj in pairs_delta
        ],
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _write_output(text: str, output_path: Optional[str]) -> None:
    """Write UTF-8 report to output_path or stdout."""
    if output_path:
        with open(output_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def _compact_markdown_report(
    snapshots: List[MetricsSnapshot],
    bench_stats: Optional[Dict[str, str]],
    perf_paths: List[str],
    perf_keys: List[str],
    hist_bucket: HistBucket,
) -> str:
    out: List[str] = []
    for i, snap in enumerate(snapshots):
        if len(snapshots) > 1:
            out.append(f"---\n\n## Snapshot {i + 1} / {len(snapshots)}\n\n")
        out.append(
            render_report(
                snap,
                bench_stats=bench_stats if i == 0 else None,
                perf_paths=perf_paths,
                perf_keys=perf_keys,
                hist_bucket=hist_bucket,
            )
        )
    return "\n".join(out)


def _ascii_report_text(
    snapshots: List[MetricsSnapshot], hist_bucket: HistBucket
) -> str:
    chunks: List[str] = []
    for i, snap in enumerate(snapshots):
        if len(snapshots) > 1:
            chunks.append(f"########## 输入 {i + 1}/{len(snapshots)} ##########\n")
        chunks.append(render_ascii_breakdown(snap, hist_bucket=hist_bucket))
    return "\n\n".join(chunks)


def _table_report_text(
    snapshots: List[MetricsSnapshot], hist_bucket: HistBucket
) -> str:
    table_lines = [
        "| cycle | client_rpc_get_µs | worker_process_get_µs | query_meta_µs | "
        "get_remote_obj_µs | remote_out_µs | urma_wait_µs | source |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for snap in snapshots:
        table_lines.append(
            render_table_row(
                snap.source_line_hint, snap, hist_bucket=hist_bucket
            )
        )
    return "\n".join(table_lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate KV perf Markdown report from metrics_summary logs.")
    ap.add_argument(
        "logs",
        nargs="*",
        default=["-"],
        help="glog or text files (default: stdin)",
    )
    ap.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Write report to FILE (UTF-8) instead of stdout (ignored if --dual-out is set)",
    )
    ap.add_argument(
        "--dual-out",
        nargs="?",
        const="output",
        default=None,
        metavar="STEM",
        help="Write STEM_total.log / STEM_delta.log / STEM.json (pretty metrics_summary bundle); "
        'default STEM=output',
    )
    ap.add_argument(
        "--bench-stats",
        metavar="FILE",
        help="Optional Key: value file for load generator summary",
    )
    ap.add_argument(
        "--last-only",
        type=lambda x: str(x).lower() in ("1", "true", "yes"),
        default=True,
        help="Only use the last metrics_summary per file (default: true)",
    )
    ap.add_argument(
        "--table",
        action="store_true",
        help="Print a compact markdown table of key avgs for every snapshot",
    )
    ap.add_argument(
        "--ascii-tree",
        action="store_true",
        help="Print two ASCII breakdown trees (key path + detail) from metrics_summary; then exit",
    )
    ap.add_argument(
        "--perf-keys",
        default="WORKER_PROCESS_GET_OBJECT,WORKER_QUERY_META,WORKER_PULL_REMOTE_DATA",
        help="Comma-separated Perf keys for optional perf table",
    )
    args = ap.parse_args()

    bench = parse_bench_stats(args.bench_stats) if args.bench_stats else None

    pairs_total = collect_summary_pairs(args.logs, args.last_only)
    snapshots_total = [snapshot_from_obj(h, o) for h, o in pairs_total]

    if not snapshots_total:
        print("No metrics_summary found.", file=sys.stderr)
        return 1

    perf_keys = [k.strip() for k in args.perf_keys.split(",") if k.strip()]
    perf_paths = list(args.logs)

    if args.dual_out is not None:
        if args.output:
            print("Note: -o/--output is ignored when --dual-out is set.", file=sys.stderr)
        stem = args.dual_out
        path_total = f"{stem}_total.log"
        path_delta = f"{stem}_delta.log"
        path_json = f"{stem}.json"
        _ensure_parent_dir(path_total)
        _ensure_parent_dir(path_delta)

        pairs_delta = summary_pairs_max_delta_per_path(args.logs)
        snapshots_delta = [snapshot_from_obj(h, o) for h, o in pairs_delta]

        if not snapshots_delta:
            print(
                "No metrics_summary for delta snapshots (unexpected).",
                file=sys.stderr,
            )
            return 1

        write_metrics_summary_json_bundle(
            path_json,
            pairs_total=pairs_total,
            pairs_delta=pairs_delta,
            last_only_total=args.last_only,
        )

        if args.ascii_tree:
            _write_output(_ascii_report_text(snapshots_total, "total"), path_total)
            _write_output(_ascii_report_text(snapshots_delta, "delta"), path_delta)
            return 0

        if args.table:
            _write_output(_table_report_text(snapshots_total, "total"), path_total)
            _write_output(_table_report_text(snapshots_delta, "delta"), path_delta)
            return 0

        _write_output(
            _compact_markdown_report(
                snapshots_total, bench, perf_paths, perf_keys, "total"
            ),
            path_total,
        )
        _write_output(
            _compact_markdown_report(
                snapshots_delta, bench, perf_paths, perf_keys, "delta"
            ),
            path_delta,
        )
        return 0

    if args.ascii_tree:
        _write_output(
            _ascii_report_text(snapshots_total, "total"),
            args.output,
        )
        return 0

    if args.table:
        _write_output(
            _table_report_text(snapshots_total, "total"),
            args.output,
        )
        return 0

    _write_output(
        _compact_markdown_report(
            snapshots_total, bench, perf_paths, perf_keys, "total"
        ),
        args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
