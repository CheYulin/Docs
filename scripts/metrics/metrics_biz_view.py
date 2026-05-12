#!/usr/bin/env python3
"""
DataSystem Worker Metrics — 业务视角仪表盘生成器 v3
=================================================
参考 worker_metrics_biz_view.html (hermes-workspace) 重构：
- 每个 Section：P99 图表 + MAX 图表并排
- JS 数据格式：扁平数组（D.key_p99[], D.key_max[], D.key_p50[]）
- Ops per Cycle：使用 delta.count（每周期增量）
- Summary 表格：P99_avg / P99_max / P50_avg / Max_avg

用法:
  python3 metrics_biz_view.py -i metrics.log -o worker_biz.html
  python3 metrics_biz_view.py -i metrics.log -o out.html --since "10:05" -v
"""

import argparse
import json
import re
import sys
import string
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 指标元数据：英文名 → 中文名 / 单位 / 描述
# ─────────────────────────────────────────────────────────────────────────────
METRIC_META = {
    # ── Write Flow ────────────────────────────────────────────────────────────
    'worker_rpc_create_meta_latency':   {'label': 'CreateMeta RPC',  'unit': 'μs', 'desc': '创建元数据 RPC'},
    'worker_process_create_latency':     {'label': 'ProcCreate',     'unit': 'μs', 'desc': '处理创建请求'},
    'worker_process_publish_latency':    {'label': 'Publish',        'unit': 'μs', 'desc': '发布数据到其他节点'},
    # ── Read Meta ─────────────────────────────────────────────────────────────
    'worker_rpc_query_meta_latency':    {'label': 'QueryMeta RPC',  'unit': 'μs', 'desc': '查询元数据 RPC'},
    'worker_get_post_query_meta_phase_latency': {'label': 'PostQuery', 'unit': 'μs', 'desc': '查询后处理（Hashring路由）'},
    'worker_get_meta_addr_hashring_latency': {'label': 'Hashring',  'unit': 'μs', 'desc': 'Hashring 查找'},
    # ── Read Data ──────────────────────────────────────────────────────────────
    'worker_process_get_latency':        {'label': 'ProcGet',        'unit': 'μs', 'desc': '处理 Get 请求'},
    'worker_get_threadpool_exec_latency': {'label': 'ThreadpoolExec','unit': 'μs', 'desc': '线程池执行'},
    'worker_get_threadpool_queue_latency': {'label': 'Threadpool Q',  'unit': 'μs', 'desc': '线程池队列等待'},
    'worker_rpc_remote_get_inbound_latency': {'label': 'Remote In',  'unit': 'μs', 'desc': '远程拉取 Inbound'},
    'worker_rpc_remote_get_outbound_latency': {'label': 'Remote Out', 'unit': 'μs', 'desc': '远程拉取 Outbound'},
    'worker_inflight_remote_get_request': {'label': 'Inflight RmtGet','unit': 'count','desc': '进行中远程请求数'},
    # ── ZMQ Queue Wait（独立展示）───────────────────────────────────────────────
    'zmq_server_req_queuing_latency':   {'label': 'Server Q Wait',  'unit': 'μs', 'desc': '服务端请求队列等待'},
    'zmq_client_req_queuing_latency':   {'label': 'Client Q Wait',  'unit': 'μs', 'desc': '客户端请求队列等待'},
    # ── URMA ─────────────────────────────────────────────────────────────────
    'worker_urma_write_latency':        {'label': 'URMA Write',     'unit': 'μs', 'desc': 'RDMA Write'},
    'worker_urma_wait_latency':          {'label': 'URMA Wait',      'unit': 'μs', 'desc': 'RDMA Wait 等待对端'},
    'urma_nanosleep_latency':           {'label': 'Nanosleep',      'unit': 'μs', 'desc': 'RDMA sleep 让出 CPU'},
    'urma_import_jfr':                  {'label': 'URMA Import JFR', 'unit': 'μs', 'desc': 'RDMA Import JFR'},
    'urma_inflight_wr_count':           {'label': 'Inflight WR',     'unit': 'count', 'desc': '进行中 RDMA Write 数'},
    # ── ZMQ Full Layer（E2E / Network / Exec / Serialize 等）──────────────────
    'zmq_rpc_e2e_latency':             {'label': 'E2E RPC',        'unit': 'μs', 'desc': '端到端 RPC'},
    'zmq_rpc_network_latency':          {'label': 'Network',         'unit': 'μs', 'desc': '网络传输'},
    'zmq_server_exec_latency':          {'label': 'Srv Exec',        'unit': 'μs', 'desc': '服务端业务执行'},
    'zmq_server_task_delay':            {'label': 'Srv Task Delay',  'unit': 'μs', 'desc': '服务端任务调度延迟'},
    'zmq_rpc_serialize_latency':        {'label': 'Serialize',       'unit': 'μs', 'desc': '序列化'},
    'zmq_rpc_deserialize_latency':      {'label': 'Deserialize',     'unit': 'μs', 'desc': '反序列化'},
    'zmq_send_io_latency':              {'label': 'Send I/O',        'unit': 'μs', 'desc': '发送 I/O'},
    'zmq_receive_io_latency':           {'label': 'Recv I/O',        'unit': 'μs', 'desc': '接收 I/O'},
    'zmq_server_rsp_queuing_latency':   {'label': 'Srv Rsp Q',       'unit': 'μs', 'desc': '服务端响应队列'},
    'zmq_client_rsp_queuing_latency':   {'label': 'Client Rsp Q',    'unit': 'μs', 'desc': '客户端响应队列'},
    'zmq_server_poll_handle_latency':   {'label': 'Poll Handle',     'unit': 'μs', 'desc': 'Poll 处理'},
    # ── Memory & Objects ───────────────────────────────────────────────────────
    'worker_allocated_memory_size':      {'label': 'Memory',          'unit': 'GB', 'desc': '已分配内存'},
    'worker_object_count':               {'label': 'Objects',          'unit': 'count', 'desc': '对象数量'},
    'worker_object_erase_total':         {'label': 'Obj Erase',        'unit': 'count', 'desc': '对象删除次数'},
    # ── Allocator ─────────────────────────────────────────────────────────────
    'worker_allocator_alloc_bytes_total': {'label': 'Alloc Bytes',    'unit': 'bytes', 'desc': '分配字节数'},
    'worker_allocator_free_bytes_total':  {'label': 'Free Bytes',     'unit': 'bytes', 'desc': '释放字节数'},
    # ── ShmRef ────────────────────────────────────────────────────────────────
    'worker_shm_ref_table_size':         {'label': 'ShmRef Size',    'unit': 'count', 'desc': 'ShmRef 表大小'},
    'worker_shm_ref_table_bytes':        {'label': 'ShmRef Bytes',   'unit': 'MB', 'desc': 'ShmRef 内存'},
    'worker_shm_ref_add_total':          {'label': 'ShmRef Add',     'unit': 'count', 'desc': '引用增加'},
    'worker_shm_ref_remove_total':       {'label': 'ShmRef Remove', 'unit': 'count', 'desc': '引用移除'},
    'worker_shm_unit_created_total':     {'label': 'ShmUnit Created','unit': 'count', 'desc': 'ShmUnit 创建'},
    'worker_shm_unit_destroyed_total':   {'label': 'ShmUnit Destoy','unit': 'count', 'desc': 'ShmUnit 销毁'},
    # ── Eviction & TTL ───────────────────────────────────────────────────────
    'worker_eviction_trigger_count':     {'label': 'Eviction Fire',   'unit': 'count', 'desc': 'Eviction 触发'},
    'worker_ttl_pending_size':          {'label': 'TTL Pending',      'unit': 'count', 'desc': 'TTL 待处理'},
    'worker_ttl_delete_success_total':   {'label': 'TTL Delete OK',   'unit': 'count', 'desc': 'TTL 删除成功'},
    'worker_ttl_fire_total':            {'label': 'TTL Fire',         'unit': 'count', 'desc': 'TTL 触发'},
    'worker_gateway_recreate_count':     {'label': 'GW Recreate',     'unit': 'count', 'desc': 'Gateway 重建'},
    'zmq_gateway_recreate_total':       {'label': 'ZMQ GW Recreate', 'unit': 'count', 'desc': 'ZMQ GW 重建'},
    'master_ttl_pending_size':         {'label': 'Master TTL Pend',  'unit': 'count', 'desc': 'Master TTL 待处理'},
    'master_ttl_delete_success_total':  {'label': 'Master TTL Del',   'unit': 'count', 'desc': 'Master TTL 删除'},
    'master_ttl_fire_total':           {'label': 'Master TTL Fire',  'unit': 'count', 'desc': 'Master TTL 触发'},
    # ── Meta Table ────────────────────────────────────────────────────────────
    'master_object_meta_table_size':     {'label': 'Master MetaTbl',  'unit': 'count', 'desc': 'Master Meta 表大小'},
}

# OPS 计数指标（key → ops 名）
OPS_METRICS = {
    'worker_rpc_create_meta_latency':   'create',
    'worker_process_publish_latency':    'publish',
    'worker_rpc_query_meta_latency':    'query_meta',
    'worker_process_get_latency':       'get',
}

# 阈值定义（key → (threshold_μs, color)）RED = 1ms, ORANGE = 500μs
THRESHOLDS = {
    'zmq_server_exec_latency':           (1000,  'red'),
    'zmq_rpc_e2e_latency':             (500,   'orange'),
    'zmq_server_req_queuing_latency':   (500,   'orange'),
    'zmq_client_req_queuing_latency':   (500,   'orange'),
    'zmq_rpc_network_latency':          (500,   'orange'),
    'zmq_server_task_delay':            (500,   'orange'),
    'zmq_server_rsp_queuing_latency':  (500,   'orange'),
    'zmq_client_rsp_queuing_latency':   (500,   'orange'),
    'worker_rpc_query_meta_latency':    (500,   'orange'),
    'worker_process_get_latency':        (500,   'orange'),
    'worker_urma_wait_latency':         (500,   'orange'),
    'worker_urma_write_latency':       (500,   'orange'),
    'urma_nanosleep_latency':          (500,   'orange'),
}

# 单位转换
def convert_value(key: str, raw: int) -> float:
    if key == 'worker_allocated_memory_size':
        return round(raw / (1024**3), 3)
    if key == 'worker_shm_ref_table_bytes':
        return round(raw / (1024**2), 3)
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Section 定义：每个 section 有 P99_KEYS / MAX_KEYS（共用）/ 是否渲染 MAX
# ─────────────────────────────────────────────────────────────────────────────
class Section:
    def __init__(self, id, title, badge, keys_p99, keys_max=None, sub_keys_p99=None,
                 sub_keys_max=None, color=None):
        self.id = id
        self.title = title
        self.badge = badge
        self.keys_p99 = keys_p99       # 主图表指标（P99 线）
        self.keys_max = keys_max or keys_p99  # MAX 图表指标（复用同一套）
        self.sub_keys_p99 = sub_keys_p99  # 子图表 P99（可选）
        self.sub_keys_max = sub_keys_max or sub_keys_p99
        self.color = color  # accent color for section header

SECTIONS = [
    # ── Stage 1: Client → Worker (ZMQ RPC Layer) ─────────────────────────────
    Section('client-worker', '📥 Client → Worker',
            'ZMQ RPC Layer: E2E / Network / Client Req+Rsp Queue',
            ['zmq_rpc_e2e_latency', 'zmq_rpc_network_latency',
             'zmq_client_req_queuing_latency', 'zmq_client_rsp_queuing_latency'],
            sub_keys_p99=['zmq_client_req_queuing_latency',
                          'zmq_client_rsp_queuing_latency'],
            color='#3b82f6'),

    # ── Stage 2: Worker Meta Write ───────────────────────────────────────────
    Section('write', '✍️ Worker Meta Write',
            'CreateMeta RPC → ProcCreate → Publish',
            ['worker_rpc_create_meta_latency', 'worker_process_publish_latency',
             'worker_process_create_latency'],
            color='#ef4444'),

    # ── Stage 3: Worker Meta Read (Query Meta) ───────────────────────────────
    Section('meta-read', '📖 Worker Meta Read',
            'QueryMeta RPC → PostQuery → ThreadpoolExec → Server Exec',
            ['worker_rpc_query_meta_latency', 'zmq_server_exec_latency'],
            sub_keys_p99=['worker_get_post_query_meta_phase_latency',
                          'worker_get_threadpool_exec_latency',
                          'zmq_server_req_queuing_latency'],
            color='#10b981'),

    # ── Stage 4: Worker Process Get (Pull Data) ─────────────────────────────
    Section('get', '📤 Worker Process Get',
            'ProcGet → ThreadpoolExec → RemoteOut',
            ['worker_process_get_latency'],
            sub_keys_p99=['worker_get_threadpool_exec_latency',
                          'worker_rpc_remote_get_outbound_latency'],
            color='#06b6d4'),

    # ── Stage 5: URMA (Data Worker) ─────────────────────────────────────────
    Section('urma', '⚙️ URMA (Data Worker)',
            'URMA Write → Nanosleep → Wait',
            ['worker_urma_write_latency', 'worker_urma_wait_latency',
             'urma_nanosleep_latency', 'worker_rpc_remote_get_inbound_latency'],
            sub_keys_p99=['worker_urma_write_latency'],
            color='#a855f7'),

    # ── Stage 6: ZMQ Full Layer (Server I/O) ───────────────────────────────
    Section('zmq-full', '🔧 ZMQ Server I/O',
            'Serialize / Send / Recv / Deserialize / Poll',
            ['zmq_rpc_serialize_latency', 'zmq_send_io_latency',
             'zmq_receive_io_latency', 'zmq_rpc_deserialize_latency',
             'zmq_server_poll_handle_latency', 'zmq_server_task_delay'],
            color='#f59e0b'),
]

# 所有需渲染的 latency metric keys（用于聚合）——从 Section 定义自动推导
ALL_LATENCY_KEYS = set()
for s in SECTIONS:
    ALL_LATENCY_KEYS.update(s.keys_p99)
    if s.sub_keys_p99:
        ALL_LATENCY_KEYS.update(s.sub_keys_p99)
    if s.keys_max:
        ALL_LATENCY_KEYS.update(s.keys_max)

# Memory / Object / Allocator / ShmRef / Eviction 单独展示（gauge/counter）
GAUGE_KEYS = [
    'worker_allocated_memory_size', 'worker_object_count',
    'worker_allocator_alloc_bytes_total', 'worker_allocator_free_bytes_total',
    'worker_shm_ref_table_size', 'worker_shm_ref_table_bytes',
    'urma_inflight_wr_count',
]
COUNTER_KEYS = [
    'worker_eviction_trigger_count', 'worker_ttl_pending_size',
    'worker_ttl_delete_success_total', 'worker_ttl_fire_total',
    'worker_gateway_recreate_count', 'zmq_gateway_recreate_total',
    'master_ttl_pending_size', 'master_ttl_delete_success_total', 'master_ttl_fire_total',
    'master_object_meta_table_size',
    'worker_shm_ref_add_total', 'worker_shm_ref_remove_total',
    'worker_shm_unit_created_total', 'worker_shm_unit_destroyed_total',
    'worker_object_erase_total',
]

# JS 中字段名映射（metric key → JS 数组变量名）
KEY_TO_JS = {k: k for k in list(ALL_LATENCY_KEYS) + GAUGE_KEYS + COUNTER_KEYS}
# 对于 sub key 中不同的命名，做映射
KEY_TO_JS['worker_get_post_query_meta_phase_latency'] = '__postquery'
KEY_TO_JS['worker_get_threadpool_exec_latency'] = '__threadpoolexec'
KEY_TO_JS['worker_process_create_latency'] = '__proccreate'


# ─────────────────────────────────────────────────────────────────────────────
# 校验 & 报告
# ─────────────────────────────────────────────────────────────────────────────
class ValidationReport:
    def __init__(self):
        self.all_metric_names_found = set()
        self.unrecognized = set()
        self.no_data = set()
        self.rendered = set()

    def add_found(self, name: str):
        self.all_metric_names_found.add(name)

    def check(self):
        all_known = set(METRIC_META.keys()) | ALL_LATENCY_KEYS | set(GAUGE_KEYS) | set(COUNTER_KEYS)
        self.unrecognized = self.all_metric_names_found - all_known
        return self

    def print_report(self, verbose: bool = False):
        print("\n" + "=" * 60)
        print("📋 指标校验报告")
        print("=" * 60)
        print(f"\n✅ 日志中共检测到 {len(self.all_metric_names_found)} 个不同指标名")
        if verbose:
            for k in sorted(self.all_metric_names_found):
                status = ''
                if k in self.unrecognized:
                    status = ' ⚠️ UNRECOGNIZED'
                elif k in self.no_data:
                    status = ' ⚠️ NO_DATA'
                elif k in self.rendered:
                    status = ' ✓ rendered'
                print(f"   {k}{status}")

        if self.unrecognized:
            print(f"\n⚠️  未识别指标:")
            for k in sorted(self.unrecognized):
                print(f"   • {k}")

        if self.no_data:
            print(f"\n⚠️  全零数据指标:")
            for k in sorted(self.no_data):
                print(f"   • {k}")

        rendered_count = len(self.rendered)
        total_found = len(self.all_metric_names_found)
        print(f"\n📊 渲染情况: {rendered_count}/{total_found} 个指标已渲染")
        print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# 日志解析
# ─────────────────────────────────────────────────────────────────────────────
class MetricsParser:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.nodes = {}
        self.cycles = {}
        self.validation = ValidationReport()

    def parse(self):
        with open(self.filepath, 'r', errors='replace') as f:
            for line in f:
                if 'metrics_summary' not in line:
                    continue
                self._parse_line(line.rstrip())
        self.validation.check()
        return self

    def _parse_line(self, line: str):
        parts = line.split('|')
        if len(parts) < 8:
            return

        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', parts[0])
        if not ts_match:
            return
        ts = ts_match.group(1).replace('T', ' ')

        node = self._extract_node(parts)
        if node not in self.nodes:
            self.nodes[node] = {'cycles': {}, 'metrics': defaultdict(dict)}

        try:
            payload = json.loads(parts[7].strip())
        except:
            try:
                payload = json.loads(parts[6].strip())
            except:
                return

        if payload.get('event') != 'metrics_summary':
            return

        cycle = payload.get('cycle')
        if not cycle:
            return
        cycle = int(cycle)

        if cycle not in self.cycles:
            self.cycles[cycle] = ts
        if cycle not in self.nodes[node]['cycles']:
            self.nodes[node]['cycles'][cycle] = ts

        for entry in payload.get('metrics', []):
            name = entry.get('name')
            if not name:
                continue

            self.validation.add_found(name)

            delta = entry.get('delta', {})
            total = entry.get('total', {})

            if isinstance(delta, dict):
                delta = {k: int(v) for k, v in delta.items()}
            elif delta:
                delta = {'value': int(delta)}
            else:
                delta = {}

            if isinstance(total, dict):
                total = {k: int(v) for k, v in total.items()}
            elif total:
                total = {'value': int(total)}
            else:
                total = {}

            if name in self.nodes[node]['metrics'].get(cycle, {}):
                old = self.nodes[node]['metrics'][cycle][name]
                old_delta = old['delta']
                old_total = old['total']

                # count 累加
                if 'count' in delta and 'count' in old_delta:
                    delta['count'] = old_delta.get('count', 0) + delta.get('count', 0)

                # latency 字段：取 non-zero delta
                for f in ('p99', 'avg_us', 'max_us', 'p50', 'p90'):
                    dv = delta.get(f, 0)
                    odv = old_delta.get(f, 0)
                    if dv == 0 and odv != 0:
                        delta[f] = odv

                # total 取 max
                for f in ('p99', 'avg_us', 'max_us', 'p50', 'p90', 'count'):
                    tv = total.get(f, 0)
                    otv = old_total.get(f, 0)
                    if tv > otv:
                        old_total[f] = tv
                total = old_total
                delta = {**old_delta, **delta}

            self.nodes[node]['metrics'][cycle][name] = {
                'delta': delta,
                'total': total,
            }

    def _extract_node(self, parts: list) -> str:
        for p in parts:
            m = re.search(r'(\d+\.\d+\.\d+\.\d+)', p)
            if m:
                return m.group(1)
        return self.filepath.stem


# ─────────────────────────────────────────────────────────────────────────────
# 数据聚合 → 扁平 JS 数据
# ─────────────────────────────────────────────────────────────────────────────
class MetricsAggregator:
    def __init__(self, parser: MetricsParser):
        self.parser = parser
        self.validation = parser.validation
        self.cycles_sorted = sorted(parser.cycles.keys(), key=lambda c: parser.cycles[c])
        self.ts_list = [parser.cycles[c] for c in self.cycles_sorted]
        self.ts_short = [t[11:19] for t in self.ts_list]

    def _seq(self, cycle_data: dict, key: str, field: str) -> list:
        """提取某指标在某 field（p99/max_us/p50/count/value）上所有 cycle 的序列"""
        result = []
        for cycle in self.cycles_sorted:
            cd = cycle_data.get(cycle, {}).get(key, {})
            delta = cd.get('delta', {})
            total = cd.get('total', {})
            # Latency: p99/max_us/p50
            if field in ('p99', 'max_us', 'p50'):
                val = delta.get(field, 0)
                if val == 0:
                    val = total.get(field, 0)
            # Counter/gauge: delta/total 直接是数值（不是嵌套对象）
            elif field == 'value':
                val = delta.get('value') or delta.get('total', 0) or delta.get('count', 0)
                if val == 0:
                    val = total.get('value') or total.get('total', 0) or total.get('count', 0)
            else:
                val = delta.get(field, 0)
                if val == 0:
                    val = total.get(field, 0)
            result.append(val)
        return result

    def _has_data(self, cycle_data: dict, key: str) -> bool:
        for cycle in self.cycles_sorted:
            cd = cycle_data.get(cycle, {}).get(key, {})
            delta = cd.get('delta', {})
            total = cd.get('total', {})
            # Latency metrics have p99/max_us/p50 fields
            if any(delta.get(f, 0) > 0 for f in ('p99', 'max_us', 'p50')):
                return True
            # Counter/gauge metrics: delta/total may be simple {value: N} or {total: N}
            # Check for any non-zero value in delta or total
            for v in list(delta.values()) + list(total.values()):
                if isinstance(v, (int, float)) and v != 0:
                    return True
            if delta or total:
                return True
        return False

    def aggregate(self) -> dict:
        node_name = list(self.parser.nodes.keys())[0]
        metrics_by_cycle = self.parser.nodes[node_name]['metrics']

        # 扁平 JS 数据
        js_data = {}
        rendered_keys = set()

        def build_flat(key: str, field: str):
            seq = self._seq(metrics_by_cycle, key, field)
            js_name = KEY_TO_JS.get(key, key)
            arr_key = f"{js_name}_{field}"
            js_data[arr_key] = seq
            return seq

        # Latency 指标（ALL_LATENCY_KEYS 来自 Section 定义）
        for key in ALL_LATENCY_KEYS:
            if self._has_data(metrics_by_cycle, key):
                build_flat(key, 'p99')
                build_flat(key, 'max_us')
                build_flat(key, 'p50')
                rendered_keys.add(key)
                self.validation.rendered.add(key)
            else:
                self.validation.no_data.add(key)

        # 其他 METRIC_META 中的 latency 指标（不在任何 Section 但有数据）
        for key in METRIC_META:
            if key in ALL_LATENCY_KEYS or key in GAUGE_KEYS or key in COUNTER_KEYS:
                continue
            if self._has_data(metrics_by_cycle, key):
                build_flat(key, 'p99')
                build_flat(key, 'max_us')
                build_flat(key, 'p50')
                rendered_keys.add(key)
                self.validation.rendered.add(key)
            else:
                self.validation.no_data.add(key)

        # Gauge / counter 指标
        for key in GAUGE_KEYS + COUNTER_KEYS:
            if self._has_data(metrics_by_cycle, key):
                build_flat(key, 'value')
                rendered_keys.add(key)
                self.validation.rendered.add(key)
            else:
                self.validation.no_data.add(key)

        # Ops（delta.count）
        for metric_key, op_name in OPS_METRICS.items():
            seq = []
            for cycle in self.cycles_sorted:
                cd = metrics_by_cycle.get(cycle, {}).get(metric_key, {})
                delta = cd.get('delta', {})
                seq.append(delta.get('count', 0))
            js_data[f"ops_{op_name}"] = seq

        # Memory GB 序列
        mem_seq = []
        for cycle in self.cycles_sorted:
            cd = metrics_by_cycle.get(cycle, {}).get('worker_allocated_memory_size', {})
            delta = cd.get('delta', {})
            val = delta.get('value', 0) or cd.get('total', {}).get('value', 0)
            mem_seq.append(convert_value('worker_allocated_memory_size', val))
        js_data['memory_gb'] = mem_seq

        # Object count 序列
        obj_seq = []
        for cycle in self.cycles_sorted:
            cd = metrics_by_cycle.get(cycle, {}).get('worker_object_count', {})
            delta = cd.get('delta', {})
            val = delta.get('value', 0) or cd.get('total', {}).get('value', 0)
            obj_seq.append(val if val else 0)
        js_data['object_count'] = obj_seq

        # Summary 统计（兼容 latency 和 counter/gauge 类型）
        summary_rows = []
        for key in rendered_keys:
            js_name = KEY_TO_JS.get(key, key)
            is_latency = key in ALL_LATENCY_KEYS
            if is_latency:
                p99_arr = js_data.get(f"{js_name}_p99", [])
                max_arr = js_data.get(f"{js_name}_max_us", [])
                p50_arr = js_data.get(f"{js_name}_p50", [])
                p99v = [v for v in p99_arr if v > 0]
                maxv = [v for v in max_arr if v > 0]
                p50v = [v for v in p50_arr if v > 0]
                if not p99v:
                    continue
                sort_key = p99v[0] if p99v else 0
                p99_avg = round(sum(p99v) / len(p99v))
                p99_max = max(p99v)
                p50_avg = round(sum(p50v) / len(p50v)) if p50v else 0
                max_avg = round(sum(maxv) / len(maxv)) if maxv else 0
                max_max = max(maxv) if maxv else 0
            else:
                # Counter/Gauge: 使用 _value 数组
                val_arr = js_data.get(f"{js_name}_value", [])
                valv = [v for v in val_arr if v > 0]
                if not valv:
                    val_arr2 = js_data.get(f"{js_name}_value", [0])
                    valv = [v for v in val_arr2 if isinstance(v, (int, float)) and v != 0]
                if not valv and val_arr:
                    valv = [v for v in val_arr if isinstance(v, (int, float))]
                if not valv:
                    continue
                sort_key = valv[-1] if valv else 0
                p99_avg = round(sum(valv) / len(valv))
                p99_max = max(valv)
                p50_avg = 0
                max_avg = p99_avg
                max_max = p99_max

            meta = METRIC_META.get(key, {})
            summary_rows.append({
                'key': key,
                'label': meta.get('label', key),
                'unit': meta.get('unit', 'μs'),
                'p99_avg': p99_avg,
                'p99_max': p99_max,
                'p50_avg': p50_avg,
                'max_avg': max_avg,
                'max_max': max_max,
                '_sort': sort_key,
            })

        # 按 _sort 降序（latency 用 p99，counter/gauge 用最新值）
        summary_rows.sort(key=lambda r: r.get('_sort', 0), reverse=True)

        # ── 阈值统计 ───────────────────────────────────────────────────────────
        # 计算每个 key 的超阈值周期
        bad_cycles = {}   # key → [cycle_indices]
        key_bad_count = {}  # key → bad_count
        key_thresholds = {}  # key → threshold
        key_max_cycle = {}  # key → (cycle_idx, max_val)
        for key, (threshold, color) in THRESHOLDS.items():
            js_name = KEY_TO_JS.get(key, key)
            p99_arr = js_data.get(f"{js_name}_p99", [])
            bad = []
            mx_val = 0
            mx_idx = -1
            for i, v in enumerate(p99_arr):
                if v > threshold:
                    bad.append(i)
                if v > mx_val:
                    mx_val = v
                    mx_idx = i
            if bad:
                bad_cycles[key] = bad
                key_bad_count[key] = len(bad)
                key_thresholds[key] = threshold
                key_max_cycle[key] = (mx_idx, mx_val)

        # 超阈值最严重的 key（用于 alert card）
        worst_key = max(key_bad_count, key=lambda k: key_bad_count[k]) if key_bad_count else None

        # Spike 周期表：超阈值最严重的 10 个 cycle index
        cycle_bad_scores = defaultdict(int)
        for key, bad_list in bad_cycles.items():
            for idx in bad_list:
                cycle_bad_scores[idx] += 1
        spike_indices = sorted(cycle_bad_scores, key=lambda i: cycle_bad_scores[i], reverse=True)[:20]
        spike_rows = []
        for idx in spike_indices:
            cycle = self.cycles_sorted[idx]
            ts = self.ts_short[idx]
            row = {'idx': idx, 'cycle': cycle, 'ts': ts}
            for key in THRESHOLDS:
                js_name = KEY_TO_JS.get(key, key)
                row[key.replace('.', '_')] = js_data.get(f"{js_name}_p99", [])[idx] if idx < len(js_data.get(f"{js_name}_p99", [])) else 0
            spike_rows.append(row)

        # 每列的 bad count for summary table
        summary_bad_counts = {}  # key → bad_count
        for key in rendered_keys:
            if key in key_bad_count:
                summary_bad_counts[key] = key_bad_count[key]

        return {
            'node': node_name,
            'time_range': f"{self.ts_list[0]} ~ {self.ts_list[-1]}",
            'cycle_count': len(self.cycles_sorted),
            'ts_short': self.ts_short,
            'cycles': self.cycles_sorted,
            'js_data': js_data,
            'summary_rows': summary_rows,
            'rendered_keys': rendered_keys,
            'thresholds': THRESHOLDS,
            'bad_cycles': bad_cycles,
            'key_bad_count': key_bad_count,
            'key_max_cycle': key_max_cycle,
            'key_thresholds': key_thresholds,
            'spike_rows': spike_rows,
            'summary_bad_counts': summary_bad_counts,
            'worst_key': worst_key,
        }


# ─────────────────────────────────────────────────────────────────────────────
# HTML 生成
# ─────────────────────────────────────────────────────────────────────────────
class HTMLGenerator:
    _SENTINEL = '__JS_INJECT__'

    def __init__(self, data: dict, sections):
        self.data = data
        self.sections = sections

    def render(self) -> str:
        page = HTML_PAGE_TEMPLATE.safe_substitute(
            node=self.data['node'],
            time_range=self.data['time_range'],
            cycle_count=self.data['cycle_count'],
            js_script=self._SENTINEL,
            sections_html=self._build_sections_html(),
            summary_rows_json=json.dumps(self.data['summary_rows'], ensure_ascii=False),
        )
        return page.replace(self._SENTINEL, self._build_js_block())

    def _build_sections_html(self) -> str:
        html = ''
        for sec in self.sections:
            # 过滤出有数据的 key
            valid_p99 = [k for k in sec.keys_p99 if k in self.data['rendered_keys']]
            valid_max = [k for k in sec.keys_max if k in self.data['rendered_keys']]
            valid_sub_p99 = [k for k in (sec.sub_keys_p99 or []) if k in self.data['rendered_keys']]
            valid_sub_max = [k for k in (sec.sub_keys_max or []) if k in self.data['rendered_keys']]
            if not valid_p99 and not valid_sub_p99:
                continue

            color_style = f'border-left-color:{sec.color}' if sec.color else ''

            html += f'<div class="section">\n'
            html += f'  <div class="section-header" style="{color_style}">\n'
            html += f'    <h2>{sec.title}</h2>\n'
            html += f'    <span class="badge">{sec.badge}</span>\n'
            html += f'  </div>\n'

            # 主图表：P99 + MAX 并排
            if valid_p99:
                html += '  <div class="chart-grid">\n'
                html += f'    <div class="chart-box">\n'
                html += f'      <h4>P99 — {" / ".join(METRIC_META.get(k,{}).get("label",k) for k in valid_p99)}</h4>\n'
                html += f'      <div id="c-{sec.id}-p99" class="chart"></div>\n'
                html += f'    </div>\n'
                html += f'    <div class="chart-box">\n'
                html += f'      <h4>MAX — {" / ".join(METRIC_META.get(k,{}).get("label",k) for k in valid_max)}</h4>\n'
                html += f'      <div id="c-{sec.id}-max" class="chart"></div>\n'
                html += f'    </div>\n'
                html += '  </div>\n'

            # 子图表（可选）
            if valid_sub_p99:
                html += '  <div class="chart-grid" style="margin-top:10px">\n'
                html += f'    <div class="chart-box">\n'
                html += f'      <h4>P99 — {" / ".join(METRIC_META.get(k,{}).get("label",k) for k in valid_sub_p99)}</h4>\n'
                html += f'      <div id="c-{sec.id}-sub-p99" class="chart"></div>\n'
                html += f'    </div>\n'
                html += f'    <div class="chart-box">\n'
                html += f'      <h4>MAX — {" / ".join(METRIC_META.get(k,{}).get("label",k) for k in valid_sub_max)}</h4>\n'
                html += f'      <div id="c-{sec.id}-sub-max" class="chart"></div>\n'
                html += f'    </div>\n'
                html += '  </div>\n'

            html += '</div>\n'

        # ── Memory & Objects ────────────────────────────────────────────────
        mem_key = 'worker_allocated_memory_size'
        obj_key = 'worker_object_count'
        if mem_key in self.data['rendered_keys'] or obj_key in self.data['rendered_keys']:
            html += '<div class="section">\n'
            html += '  <div class="section-header" style="border-left-color:#7c3aed">\n'
            html += '    <h2>🧠 Memory & Objects</h2>\n'
            html += '  </div>\n'
            html += '  <div class="chart-grid">\n'
            if mem_key in self.data['rendered_keys']:
                html += '    <div class="chart-box">\n'
                html += '      <h4>Memory (GB)</h4>\n'
                html += '      <div id="c-memory" class="chart"></div>\n'
                html += '    </div>\n'
            if obj_key in self.data['rendered_keys']:
                html += '    <div class="chart-box">\n'
                html += '      <h4>Object Count</h4>\n'
                html += '      <div id="c-objects" class="chart"></div>\n'
                html += '    </div>\n'
            html += '  </div>\n'
            html += '</div>\n'

        return html

    def _build_js_block(self) -> str:
        d = {
            'TL': self.data['ts_short'],
            'cycles': self.data['cycles'],
        }
        # 扁平数据
        for k, v in self.data['js_data'].items():
            d[k] = v

        script = '<script>\n'
        script += f'var D = {json.dumps(d, ensure_ascii=False)};\n'
        script += HTML_JS_INIT
        script += '\n</script>\n'
        return script


# ─────────────────────────────────────────────────────────────────────────────
# HTML 模板
# ─────────────────────────────────────────────────────────────────────────────
HTML_PAGE_TEMPLATE = string.Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Worker Metrics — 业务视角</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#f0f4f8; color:#1e293b; font-size:13px; }
.header { background:linear-gradient(135deg,#3b82f6,#6366f1); color:#fff; padding:18px 24px; }
.header h1 { font-size:18px; font-weight:600; color:#fff; margin:0; }
.header .meta { font-size:11px; opacity:0.85; margin-top:3px; }
.container { max-width:1600px; margin:0 auto; padding:14px 18px; }

.summary { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:14px; }
.card { background:#fff; border-radius:10px; padding:12px 16px; box-shadow:0 1px 4px rgba(0,0,0,0.08); border-left:3px solid #3b82f6; min-width:120px; }
.card.o { border-left-color:#f59e0b; }
.card.r { border-left-color:#ef4444; }
.card.g { border-left-color:#22c55e; }
.card.p { border-left-color:#a855f7; }
.card.c { border-left-color:#06b6d4; }
.card .lbl { font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:3px; }
.card .val { font-size:22px; font-weight:700; color:#1e293b; }
.card .sub { font-size:10px; color:#94a3b8; margin-top:2px; }

.alert-box { background:#fef3c7; border-left:3px solid #f59e0b; padding:8px 14px; border-radius:0 6px 6px 0; margin:8px 0; font-size:12px; }
.alert-box strong { color:#b45309; }
.alert-box.blue { background:#dbeafe; border-color:#3b82f6; }
.alert-box.blue strong { color:#1d4ed8; }
.alert-box.green { background:#d1fae5; border-color:#10b981; }
.alert-box.green strong { color:#047857; }
.alert-box.red { background:#fee2e2; border-color:#dc2626; }
.alert-box.red strong { color:#b91c1c; }

.badge { display:inline-block; padding:1px 6px; border-radius:5px; font-size:9px; font-weight:600; }
.badge-green { background:#d1fae5; color:#047857; }
.badge-yellow { background:#fef3c7; color:#b45309; }
.badge-red { background:#fee2e2; color:#b91c1c; }
.badge-blue { background:#dbeafe; color:#1d4ed8; }

.section { margin-bottom:18px; }
.section-header { display:flex; align-items:center; gap:10px; margin-bottom:8px; padding-bottom:6px; border-bottom:2px solid #e2e8f0; padding-left:8px; }
.section-header h2 { font-size:13px; font-weight:600; color:#334; }
.section-header .badge { font-size:9px; padding:2px 8px; border-radius:10px; background:#f1f5f9; color:#64748b; }
.chart-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.chart-box { background:#fff; border-radius:10px; padding:12px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }
.chart-box h4 { font-size:11px; color:#475569; font-weight:500; margin-bottom:6px; }
.chart { height:200px; }
.section-title { font-size:12px; font-weight:600; color:#475569; margin:14px 0 7px; padding-top:10px; border-top:1px solid #e2e8f0; }
.table-wrap { background:#fff; border-radius:8px; box-shadow:0 1px 4px rgba(0,0,0,0.06); overflow:auto; max-height:280px; }
table { width:100%; border-collapse:collapse; font-size:11px; }
th { background:#f8fafc; color:#64748b; padding:6px 10px; text-align:left; font-weight:600; border-bottom:2px solid #e2e8f0; white-space:nowrap; position:sticky; top:0; z-index:1; }
td { padding:5px 10px; border-bottom:1px solid #f1f5f9; color:#334155; }
td.num { text-align:right; }
tr:hover td { background:#f8fafc; }
th.num { text-align:right; }
</style>
</head>
<body>

<div class="header">
  <h1>Worker Metrics — 业务视角</h1>
  <div class="meta">节点: $node &nbsp;|&nbsp; $time_range &nbsp;|&nbsp; 采样周期: 5s &nbsp;|&nbsp; 共 $cycle_count 周期</div>
</div>

<div class="container">

<!-- Alert Boxes -->
<div id="alert-boxes"></div>

<!-- Summary Cards -->
<div class="summary" id="summary-cards"></div>

<!-- Ops per Cycle -->
<div class="section">
  <div class="section-header" style="border-left-color:#3b82f6">
    <h2>📊 Ops per Cycle — 流量模型</h2>
    <span class="badge">Write = Create + Publish &nbsp;|&nbsp; Read = Get</span>
  </div>
  <div class="chart-box" style="max-width:900px">
    <h4>堆叠柱状图</h4>
    <div id="c-ops" class="chart" style="height:220px"></div>
  </div>
</div>

<!-- Dynamic Sections -->
$sections_html

<!-- Spike Cycle Detail Table -->
<div class="section-title" id="spike-title" style="display:none">⚠️ 异常周期详情</div>
<div class="table-wrap" id="spike-table-wrap" style="display:none; margin-bottom:16px">
<table>
<thead id="spike-thead"></thead>
<tbody id="spike-tbody"></tbody>
</table>
</div>

<!-- Summary Table -->
<div class="section-title">Latency Breakdown</div>
<div class="table-wrap" style="margin-bottom:16px">
<table>
<thead>
  <tr>
    <th>指标</th>
    <th class="num">P99 Avg</th>
    <th class="num">P99 Max</th>
    <th class="num">P50 Avg</th>
    <th class="num">Max Avg</th>
    <th class="num">Max Max</th>
    <th class="num">超阈值周期</th>
    <th>状态</th>
    <th>单位</th>
  </tr>
</thead>
<tbody id="tbl-lat"></tbody>
</table>
</div>

</div>

$js_script
</body>
</html>
""")


# ─────────────────────────────────────────────────────────────────────────────
# JS 初始化
# ─────────────────────────────────────────────────────────────────────────────
HTML_JS_INIT = r"""
var TL = D.TL;
var CYCLES = D.cycles;
var SUMMARY_ROWS = [];
var SPIKE_ROWS = typeof SPIKE_ROWS !== 'undefined' ? SPIKE_ROWS : [];
var BAD_COUNTS = typeof BAD_COUNTS !== 'undefined' ? BAD_COUNTS : {};
var THRESHOLD_DATA = typeof THRESHOLD_DATA !== 'undefined' ? THRESHOLD_DATA : {};

// ── Base chart config ─────────────────────────────────────────────────────────
function mkBase() {
  return {
    backgroundColor: 'transparent',
    grid: { top: 30, bottom: 34, left: 58, right: 18 },
    xAxis: {
      type: 'category', data: TL,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#94a3b8', fontSize: 9, rotate: 30 },
      splitLine: { show: false }
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#94a3b8', fontSize: 9 },
      splitLine: { lineStyle: { color: '#f1f5f9' }, show: true }
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: '#e2e8f0', borderWidth: 1,
      textStyle: { color: '#334', fontSize: 10 },
      axisPointer: { type: 'cross', crossStyle: { color: '#cbd5e1' } }
    },
    legend: { top: 4, right: 8, textStyle: { color: '#64748b', fontSize: 8 }, itemWidth: 14, itemHeight: 7 },
  };
}

function mkChart(id, series) {
  var el = document.getElementById(id);
  if (!el) return;
  var chart = echarts.init(el);
  var opts = mkBase();
  opts.series = series;
  chart.setOption(opts);
  return chart;
}

function lineSeries(name, data, color, dashed) {
  return {
    name: name, type: 'line', data: data,
    smooth: false, symbol: 'circle', symbolSize: 3,
    lineStyle: { width: 1.5, type: dashed ? 'dashed' : 'solid' },
    itemStyle: { color: color }
  };
}

function colorFor(i) {
  var C = ['#3b82f6','#f59e0b','#ef4444','#22c55e','#a855f7','#06b6d4','#64748b','#10b981','#ec4899','#14b8a6'];
  return C[i % C.length];
}

// ── Series builder from key list ──────────────────────────────────────────────
function buildSeries(keys, suffix, colorFn, dashedFn) {
  var series = [];
  keys.forEach(function(k, i) {
    var arr = D[k + '_' + suffix];
    if (!arr || !arr.filter(function(v){return v>0;}).length) return;
    series.push(lineSeries(
      METRIC_LABELS[k] || k,
      arr, colorFn(i), dashedFn ? dashedFn(i) : false
    ));
  });
  return series;
}

// ── Metric labels (must match METRIC_META keys) ───────────────────────────────
var METRIC_LABELS = {
  'worker_rpc_create_meta_latency': 'CreateMeta RPC',
  'worker_process_create_latency': 'ProcCreate',
  'worker_process_publish_latency': 'Publish',
  'worker_rpc_query_meta_latency': 'QueryMeta RPC',
  'worker_get_post_query_meta_phase_latency': 'PostQuery',
  'worker_get_meta_addr_hashring_latency': 'Hashring',
  'worker_process_get_latency': 'ProcGet',
  'worker_get_threadpool_exec_latency': 'ThreadpoolExec',
  'worker_get_threadpool_queue_latency': 'Threadpool Q',
  'worker_rpc_remote_get_inbound_latency': 'Remote In',
  'worker_rpc_remote_get_outbound_latency': 'Remote Out',
  'worker_inflight_remote_get_request': 'Inflight RmtGet',
  'worker_urma_write_latency': 'URMA Write',
  'worker_urma_wait_latency': 'URMA Wait',
  'urma_nanosleep_latency': 'Nanosleep',
  'urma_import_jfr': 'URMA Import JFR',
  'urma_inflight_wr_count': 'Inflight WR',
  'zmq_server_req_queuing_latency': 'Server Q Wait',
  'zmq_client_req_queuing_latency': 'Client Q Wait',
  'zmq_rpc_e2e_latency': 'E2E RPC',
  'zmq_rpc_network_latency': 'Network',
  'zmq_server_exec_latency': 'Srv Exec',
  'zmq_server_task_delay': 'Srv Task Delay',
  'zmq_rpc_serialize_latency': 'Serialize',
  'zmq_rpc_deserialize_latency': 'Deserialize',
  'zmq_send_io_latency': 'Send I/O',
  'zmq_receive_io_latency': 'Recv I/O',
  'zmq_server_rsp_queuing_latency': 'Srv Rsp Q',
  'zmq_client_rsp_queuing_latency': 'Client Rsp Q',
  'zmq_server_poll_handle_latency': 'Poll Handle',
  'worker_allocated_memory_size': 'Memory',
  'worker_object_count': 'Objects',
  'worker_allocator_alloc_bytes_total': 'Alloc Bytes',
  'worker_allocator_free_bytes_total': 'Free Bytes',
  'worker_shm_ref_table_size': 'ShmRef Size',
  'worker_shm_ref_table_bytes': 'ShmRef Bytes',
  'urma_inflight_wr_count': 'Inflight WR',
  'worker_eviction_trigger_count': 'Eviction Fire',
  'worker_ttl_pending_size': 'TTL Pending',
  'worker_ttl_delete_success_total': 'TTL Delete OK',
  'worker_ttl_fire_total': 'TTL Fire',
  'worker_gateway_recreate_count': 'GW Recreate',
  'zmq_gateway_recreate_total': 'ZMQ GW Recreate',
  'master_ttl_pending_size': 'Master TTL Pend',
  'master_ttl_delete_success_total': 'Master TTL Del',
  'master_ttl_fire_total': 'Master TTL Fire',
  'master_object_meta_table_size': 'Master MetaTbl',
  'worker_shm_ref_add_total': 'ShmRef Add',
  'worker_shm_ref_remove_total': 'ShmRef Remove',
  'worker_shm_unit_created_total': 'ShmUnit Created',
  'worker_shm_unit_destroyed_total': 'ShmUnit Destoy',
  'worker_object_erase_total': 'Obj Erase',
};

// ── Ops Chart (stacked bar) ───────────────────────────────────────────────────
(function() {
  var el = document.getElementById('c-ops');
  if (!el) return;
  var opsChart = echarts.init(el);
  opsChart.setOption({
    backgroundColor: 'transparent',
    grid: { top: 20, bottom: 34, left: 58, right: 18 },
    xAxis: {
      type: 'category', data: TL,
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#94a3b8', fontSize: 9, rotate: 30 },
      splitLine: { show: false }
    },
    yAxis: {
      type: 'value',
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#94a3b8', fontSize: 9 },
      splitLine: { lineStyle: { color: '#f1f5f9' }, show: true }
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: '#e2e8f0', borderWidth: 1,
      textStyle: { color: '#334', fontSize: 10 },
      axisPointer: { type: 'cross', crossStyle: { color: '#cbd5e1' } }
    },
    legend: { top: 4, right: 8, textStyle: { color: '#64748b', fontSize: 8 }, itemWidth: 14, itemHeight: 7 },
    series: [
      { name: 'Write (Create)', type: 'bar', stack: 'ops', data: D.ops_create || [], itemStyle: { color: '#ef4444' }, barMaxWidth: 40 },
      { name: 'Write (Publish)', type: 'bar', stack: 'ops', data: D.ops_publish || [], itemStyle: { color: '#f59e0b' }, barMaxWidth: 40 },
      { name: 'Read (Get)', type: 'bar', stack: 'ops', data: D.ops_get || [], itemStyle: { color: '#3b82f6' }, barMaxWidth: 40 },
      { name: 'Query Meta', type: 'bar', stack: 'ops', data: D.ops_query_meta || [], itemStyle: { color: '#22c55e' }, barMaxWidth: 40 }
    ]
  });
})();

// ── Alert Boxes ─────────────────────────────────────────────────────────────
(function() {
  var totalCycles = CYCLES.length;
  var alertEls = [];

  // Build per-metric bad cycle alerts
  Object.keys(BAD_COUNTS).forEach(function(key) {
    var count = BAD_COUNTS[key];
    if (!count) return;
    var pct = ((count / totalCycles) * 100).toFixed(1);
    var thrInfo = THRESHOLD_DATA[key];
    if (!thrInfo) return;
    var color = thrInfo.color; // 'red' or 'orange'
    var threshold = thrInfo.threshold;
    var label = METRIC_LABELS[key] || key;
    var alertClass = color === 'red' ? 'red' : 'blue';
    var thrLabel = threshold >= 1000 ? (threshold/1000)+'ms' : threshold+'μs';
    alertEls.push({
      cls: alertClass,
      text: '<strong>' + label + '</strong> 超 ' + thrLabel + ' 阈值: ' + count + ' 个周期 (' + pct + '%)'
    });
  });

  var alertsHtml = alertEls.map(function(a) {
    return '<div class="alert-box ' + a.cls + '">' + a.text + '</div>';
  }).join('');
  document.getElementById('alert-boxes').innerHTML = alertsHtml;
})();

// ── Summary cards ─────────────────────────────────────────────────────────────
(function() {
  var rows = SUMMARY_ROWS;
  rows.sort(function(a, b) { return b.p99_avg - a.p99_avg; });
  var el = document.getElementById('summary-cards');
  var colors = ['','o','r','g','p','c'];
  rows.slice(0, 10).forEach(function(r, i) {
    el.innerHTML +=
      '<div class="card ' + (colors[i % colors.length]) + '">' +
      '<div class="lbl">' + r.label + ' P99 Avg</div>' +
      '<div class="val">' + r.p99_avg + '<span style="font-size:13px;color:#64748b">' + r.unit + '</span></div>' +
      '<div class="sub">P99 Max=' + r.p99_max + ' ' + r.unit + '</div>' +
      '</div>';
  });
})();

// ── Latency table with bad cycle counts ──────────────────────────────────────
(function() {
  var rows = SUMMARY_ROWS;
  rows.sort(function(a, b) { return b.p99_avg - a.p99_avg; });
  var tbl = document.getElementById('tbl-lat');
  rows.forEach(function(r) {
    var key = r.key;
    var badCount = (BAD_COUNTS && key && BAD_COUNTS[key]) ? BAD_COUNTS[key] : 0;
    var totalCycles = CYCLES.length;
    var pct = totalCycles > 0 ? ((badCount / totalCycles) * 100).toFixed(1) : '0';
    var badgeCls = badCount === 0 ? 'badge-green' : (badCount < totalCycles * 0.05 ? 'badge-yellow' : 'badge-red');
    var badgeText = badCount === 0 ? '正常' : badCount + '周期(' + pct + '%)';
    tbl.innerHTML += '<tr>' +
      '<td>' + r.label + '</td>' +
      '<td class="num">' + r.p99_avg + '</td>' +
      '<td class="num">' + r.p99_max + '</td>' +
      '<td class="num">' + r.p50_avg + '</td>' +
      '<td class="num">' + r.max_avg + '</td>' +
      '<td class="num">' + r.max_max + '</td>' +
      '<td class="num">' + badCount + '/' + totalCycles + '</td>' +
      '<td><span class="badge ' + badgeCls + '">' + badgeText + '</span></td>' +
      '<td>' + r.unit + '</td>' +
      '</tr>';
  });
})();

// ── Spike cycle table ──────────────────────────────────────────────────────
(function() {
  if (!SPIKE_ROWS || SPIKE_ROWS.length === 0) return;
  // Determine which columns to show based on available data
  var keys = ['worker_rpc_query_meta_latency','worker_process_get_latency','zmq_server_exec_latency','zmq_rpc_e2e_latency','zmq_server_req_queuing_latency','zmq_client_req_queuing_latency','zmq_rpc_network_latency','zmq_server_task_delay'];
  var shownKeys = keys.filter(function(k){ return D[k+'_p99'] && D[k+'_p99'].some(function(v){return v>0;}); });
  if (shownKeys.length === 0) return;

  // Show section
  document.getElementById('spike-title').style.display = 'block';
  document.getElementById('spike-table-wrap').style.display = 'block';

  // Build header
  var thead = document.getElementById('spike-thead');
  var hdr = '<tr><th>Cycle</th><th>Time</th>';
  shownKeys.forEach(function(k){ hdr += '<th class="num">' + (METRIC_LABELS[k]||k) + ' P99</th>'; });
  hdr += '<th>状态</th></tr>';
  thead.innerHTML = hdr;

  // Build rows
  var tbody = document.getElementById('spike-tbody');
  SPIKE_ROWS.forEach(function(row) {
    var tr = '<tr><td>' + row.cycle + '</td><td>' + row.ts + '</td>';
    shownKeys.forEach(function(k){
      tr += '<td class="num">' + (row[k] || 0) + '</td>';
    });
    // Status badge based on exec p99
    var execP99 = row['zmq_server_exec_latency'] || 0;
    var statusCls = execP99 > 1000 ? 'badge-red' : 'badge-green';
    var statusTxt = execP99 > 1000 ? 'SPIKE' : '正常';
    tr += '<td><span class="badge ' + statusCls + '">' + statusTxt + '</span></td>';
    tr += '</tr>';
    tbody.innerHTML += tr;
  });
})();

// ── Memory chart ──────────────────────────────────────────────────────────────
(function() {
  var el = document.getElementById('c-memory');
  if (!el || !D.memory_gb) return;
  mkChart('c-memory', [lineSeries('Memory (GB)', D.memory_gb, '#7c3aed', false)]);
})();

// ── Objects chart ─────────────────────────────────────────────────────────────
(function() {
  var el = document.getElementById('c-objects');
  if (!el || !D.object_count) return;
  mkChart('c-objects', [lineSeries('Object Count', D.object_count, '#06b6d4', false)]);
})();

// ── Dynamic section charts ─────────────────────────────────────────────────────
var SECTIONS_CFG = [
  // Stage 1: Client → Worker (ZMQ RPC Layer)
  { id: 'client-worker', keys_p99: ['zmq_rpc_e2e_latency','zmq_rpc_network_latency'], sub_keys_p99: ['zmq_client_req_queuing_latency','zmq_client_rsp_queuing_latency'] },
  // Stage 2: Worker Meta Write
  { id: 'write', keys_p99: ['worker_rpc_create_meta_latency','worker_process_publish_latency','worker_process_create_latency'] },
  // Stage 3: Worker Meta Read
  { id: 'meta-read', keys_p99: ['worker_rpc_query_meta_latency','zmq_server_exec_latency'], sub_keys_p99: ['worker_get_post_query_meta_phase_latency','worker_get_threadpool_exec_latency','zmq_server_req_queuing_latency'] },
  // Stage 4: Worker Process Get
  { id: 'get', keys_p99: ['worker_process_get_latency'], sub_keys_p99: ['worker_get_threadpool_exec_latency','worker_rpc_remote_get_outbound_latency'] },
  // Stage 5: URMA (Data Worker)
  { id: 'urma', keys_p99: ['worker_urma_write_latency','worker_urma_wait_latency','urma_nanosleep_latency','worker_rpc_remote_get_inbound_latency'], sub_keys_p99: ['worker_urma_write_latency'] },
  // Stage 6: ZMQ Server I/O
  { id: 'zmq-full', keys_p99: ['zmq_rpc_serialize_latency','zmq_send_io_latency','zmq_receive_io_latency','zmq_rpc_deserialize_latency','zmq_server_poll_handle_latency','zmq_server_task_delay'] },
];

SECTIONS_CFG.forEach(function(cfg) {
  // P99 chart
  var p99Keys = cfg.keys_p99.filter(function(k) {
    var arr = D[k + '_p99'];
    return arr && arr.filter(function(v){return v>0;}).length;
  });
  if (p99Keys.length) {
    var p99Series = p99Keys.map(function(k, i) {
      return lineSeries(METRIC_LABELS[k]||k, D[k+'_p99'], colorFor(i), false);
    });
    mkChart('c-' + cfg.id + '-p99', p99Series);
  }
  // MAX chart
  var maxKeys = (cfg.keys_max || cfg.keys_p99).filter(function(k) {
    var arr = D[k + '_max_us'];
    return arr && arr.filter(function(v){return v>0;}).length;
  });
  if (maxKeys.length) {
    var maxSeries = maxKeys.map(function(k, i) {
      return lineSeries((METRIC_LABELS[k]||k) + ' MAX', D[k+'_max_us'], colorFor(i), false);
    });
    mkChart('c-' + cfg.id + '-max', maxSeries);
  }
  // Sub P99
  if (cfg.sub_keys_p99) {
    var subP99Keys = cfg.sub_keys_p99.filter(function(k) {
      var arr = D[k + '_p99'];
      return arr && arr.filter(function(v){return v>0;}).length;
    });
    if (subP99Keys.length) {
      var subP99Series = subP99Keys.map(function(k, i) {
        return lineSeries(METRIC_LABELS[k]||k, D[k+'_p99'], colorFor(i), true);
      });
      mkChart('c-' + cfg.id + '-sub-p99', subP99Series);
    }
    var subMaxKeys = cfg.sub_keys_p99.filter(function(k) {
      var arr = D[k + '_max_us'];
      return arr && arr.filter(function(v){return v>0;}).length;
    });
    if (subMaxKeys.length) {
      var subMaxSeries = subMaxKeys.map(function(k, i) {
        return lineSeries((METRIC_LABELS[k]||k) + ' MAX', D[k+'_max_us'], colorFor(i), true);
      });
      mkChart('c-' + cfg.id + '-sub-max', subMaxSeries);
    }
  }
});

// ── Resize handler ────────────────────────────────────────────────────────────
window.addEventListener('resize', function() {
  echarts.getAllCharts().forEach(function(c) { c.resize(); });
});
"""


# ─────────────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────────────
def _parse_ts(ts_str):
    m = re.match(r'^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$', ts_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                       int(m.group(4)), int(m.group(5)), int(m.group(6)))
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})', ts_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                       int(m.group(4)), int(m.group(5)), int(m.group(6)))
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})', ts_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                       int(m.group(4)), int(m.group(5)), int(m.group(6)))
    return None


def _parse_since_ts(since_str, parser):
    base_year, base_month, base_day = 2026, 5, 10
    try:
        with open(parser.filepath, 'r', errors='replace') as f:
            for line in f:
                m = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})', line)
                if m:
                    base_year, base_month, base_day = int(m.group(1)), int(m.group(2)), int(m.group(3))
                    break
    except Exception:
        pass

    since_str = since_str.strip()
    m = re.match(r'^(\d{1,2}):(\d{2})$', since_str)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        return datetime(base_year, base_month, base_day, h, mi, 0)

    m = re.match(r'^(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})$', since_str)
    if m:
        y, mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        return datetime(2000 + y, mo, d, h, mi, 0)

    m = re.match(r'^(\d{2})(\d{2})(\d{2})\s+(\d{2})(\d{2})$', since_str)
    if m:
        y, mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        return datetime(2000 + y, mo, d, h, mi, 0)

    # YYMMDDHHMM (no separator, 10 digits)
    m = re.match(r'^(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$', since_str)
    if m:
        y, mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        return datetime(2000 + y, mo, d, h, mi, 0)

    # MMDDHHMM (no separator, 8 digits - month/day/hour/min)
    m = re.match(r'^(\d{2})(\d{2})(\d{2})(\d{2})$', since_str)
    if m:
        mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        return datetime(base_year, base_month, d, h, mi, 0)

    return None


def _filter_cycles_since(parser, since_dt):
    if since_dt is None:
        return
    cycles_to_remove = []
    for cycle, ts in parser.cycles.items():
        dt = _parse_ts(ts)
        if dt is None or dt < since_dt:
            cycles_to_remove.append(cycle)
    for cycle in cycles_to_remove:
        del parser.cycles[cycle]
        for node in parser.nodes.values():
            if cycle in node.get('cycles', {}):
                del node['cycles'][cycle]
            if cycle in node.get('metrics', {}):
                del node['metrics'][cycle]


# ─────────────────────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Worker Metrics 业务视角仪表盘生成器 v3")
    parser.add_argument('--input', '-i', required=True)
    parser.add_argument('--output', '-o', default='worker_biz.html')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--since', '-s', default=None,
                        help='只保留指定时间之后的数据: HH:MM 或 YYMMDD_HHMM')
    args = parser.parse_args()

    input_path = Path(args.input)
    if input_path.is_dir():
        files = list(input_path.glob('*.log')) + list(input_path.glob('*.log.gz'))
        if not files:
            print("no .log files found")
            sys.exit(1)
        input_path = sorted(files, key=lambda f: f.stat().st_mtime)[-1]
        print(f"using: {input_path.name}")

    print(f"parsing: {input_path}")
    metrics_parser = MetricsParser(input_path).parse()

    if not metrics_parser.nodes:
        print("no metrics data found")
        sys.exit(1)

    node_name = list(metrics_parser.nodes.keys())[0]
    cycles = len(metrics_parser.cycles)
    print(f"   node: {node_name}, cycles before filter: {cycles}")

    if args.since:
        since_dt = _parse_since_ts(args.since, metrics_parser)
        print(f"   filtering since {since_dt}")
        _filter_cycles_since(metrics_parser, since_dt)
        cycles_after = len(metrics_parser.cycles)
        print(f"   cycles after filter: {cycles_after} ({cycles - cycles_after} removed)")

    aggregator = MetricsAggregator(metrics_parser)
    data = aggregator.aggregate()

    metrics_parser.validation.print_report(verbose=args.verbose)

    html_gen = HTMLGenerator(data, SECTIONS)
    html = html_gen.render()

    # inject Python-computed data
    html = html.replace(
        'var SUMMARY_ROWS = [];',
        f'var SUMMARY_ROWS = {json.dumps(data["summary_rows"], ensure_ascii=False)};'
    )
    html = html.replace(
        'var SPIKE_ROWS = typeof SPIKE_ROWS !== \'undefined\' ? SPIKE_ROWS : [];',
        f'var SPIKE_ROWS = {json.dumps(data["spike_rows"], ensure_ascii=False)};'
    )

    # Build BAD_COUNTS (key → count)
    bad_counts = {k: v for k, v in data['key_bad_count'].items()}
    html = html.replace(
        'var BAD_COUNTS = typeof BAD_COUNTS !== \'undefined\' ? BAD_COUNTS : {};',
        f'var BAD_COUNTS = {json.dumps(bad_counts, ensure_ascii=False)};'
    )

    # Build THRESHOLD_DATA (key → {threshold, color})
    thr_data = {k: {'threshold': data['key_thresholds'].get(k, 0), 'color': data['thresholds'].get(k, (0,'orange'))[1]} for k in bad_counts}
    html = html.replace(
        'var THRESHOLD_DATA = typeof THRESHOLD_DATA !== \'undefined\' ? THRESHOLD_DATA : {};',
        f'var THRESHOLD_DATA = {json.dumps(thr_data, ensure_ascii=False)};'
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)

    size_kb = len(html.encode('utf-8')) // 1024
    print(f"\ngenerated: {out_path} ({size_kb}KB)")


if __name__ == '__main__':
    main()
