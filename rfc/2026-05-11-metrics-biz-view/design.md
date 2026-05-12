# Metrics 可观测 — 业务视角仪表盘：设计摘要

## 概述

将 `metrics_summary` 日志解析为 ECharts 可视化网页，支持完整 45 个指标分组、任意时间窗口过滤。

**成果**：输出 ~100KB HTML（vs 1MB+ 原始），减少 **90%+**；Python 脚本 + Markdown 文档，完全可控；CDN 加载 ECharts（约 300KB，浏览器缓存复用）。

---

## 设计原则

### ECharts CDN 外链

```html
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
```

内网环境需将 ECharts 下载到本地并修改 `script src`。

### 数据与渲染分离

- **Python 端**：解析日志、合并同 cycle 多 part_index 数据、聚合计算、注入 `D = {...}` 变量
- **HTML/JS 端**：模板渲染、图表初始化，Python 不生成任何 ECharts 配置

### 预计算优先

P99/Avg/Max/P50 等统计量在 Python 端算好，直接注入。HTML 只做 `forEach` 渲染，不做复杂计算。

### 同 Cycle 多 Part_index 合并策略

日志中同一 cycle 的数据可能来自不同 `part_index`（如 part_index=1 全0，part_index=3 有数据），合并逻辑：

- **latency 字段（p99/avg_us/max_us/p50/p90）**：优先取 non-zero delta；两者都为零则取 total 较大者
- **count 字段**：累加
- **total 累计值**：取 max（只增不减）

---

## 数据流

```
日志文件 (metrics_summary)
    │
    ▼
MetricsParser  ─── 解析分隔行 ───→  {cycle: {metric_name: {total, delta}}}
    │
    ▼
（可选）_filter_cycles_since()  ─── 时间过滤 ───→  丢弃早于 --since 的 cycle
    │
    ▼
MetricsAggregator  ─── 预计算 + 分组 ───→  {
    node, time_range, cycle_count,
    TL[], cycles[],
    series: {metric_name: {label, unit, p99[], avg[], max[], p50[]}},
    summary: {metric_name: {p99_avg, p99_max, ...}},
    ops: {create[], publish[], get[]}
}
    │
    ▼
HTMLGenerator.render()  ─── string.Template ───→  worker_biz.html（含 D = {...}）
    │
    ▼
浏览器加载 ── CDN 获取 ECharts ── 渲染图表
```

---

## 指标分组（v0.8.1.rc23 全部 45 个指标）

| 分组 | 指标 | 说明 |
|------|------|------|
| **Write Flow** | `worker_rpc_create_meta_latency`, `worker_process_create_latency`, `worker_process_publish_latency` | 写路径 |
| **Write Flow → ZMQ RPC** | ZMQ RPC 12 个指标 | client/server queuing、poll、exec、e2e、serialize 等 |
| **Read Meta** | `worker_rpc_query_meta_latency`, `worker_get_post_query_meta_phase_latency`, `worker_get_meta_addr_hashring_latency` | 查询元数据 |
| **Read Data** | `worker_process_get_latency`, `worker_get_threadpool_exec_latency`, `worker_get_threadpool_queue_latency`, `worker_rpc_remote_get_inbound_latency`, `worker_rpc_remote_get_outbound_latency`, `worker_inflight_remote_get_request` | 拉取数据 |
| **Read Data → ZMQ RPC** | ZMQ RPC 12 个指标 | 同上 |
| **URMA** | `worker_urma_write_latency`, `worker_urma_wait_latency`, `urma_nanosleep_latency`, `urma_inflight_wr_count`, `urma_import_jfr` | RDMA 操作 |
| **Memory & Objects** | `worker_allocated_memory_size`, `worker_object_count`, `worker_object_erase_total` | 内存对象 |
| **Allocator** | `worker_allocator_alloc_bytes_total`, `worker_allocator_free_bytes_total` | 分配器 |
| **ShmRef Table** | `worker_shm_ref_table_size`, `worker_shm_ref_table_bytes`, `worker_shm_ref_add_total`, `worker_shm_ref_remove_total`, `worker_shm_unit_created_total`, `worker_shm_unit_destroyed_total` | 共享内存引用 |
| **Eviction & TTL** | `worker_eviction_trigger_count`, `worker_ttl_pending_size`, `worker_ttl_delete_success_total`, `worker_ttl_fire_total`, `worker_gateway_recreate_count`, `zmq_gateway_recreate_total`, `master_ttl_pending_size`, `master_ttl_delete_success_total`, `master_ttl_fire_total` | 淘汰与 TTL |
| **Meta Table** | `master_object_meta_table_size` | 元数据表 |

> **注意**：日志中实际存在 3 个旧指标（`zmq_client_queuing_latency`、`zmq_server_queue_wait_latency`、`zmq_server_reply_latency`）已废弃，代码中用 `extra_keys` 兜底处理但不渲染。

---

## JS 数据格式

```javascript
var D = {
  "TL": ["17:10:01", "17:10:06", "17:10:11", ...],   // 时间标签
  "cycles": [825, 826, 827, ...],                     // cycle 编号
  "series": {
    "zmq_server_rsp_queuing_latency": {
      "label": "Server Rsp Q",
      "unit": "μs",
      "p99": [99, 99, 98, ...],
      "avg": [26, 27, 27, ...],
      "max": [1223, 3483, 957, ...],
      "p50": [88, 90, 89, ...]
    }
  },
  "ops": { "create": [...], "publish": [...], "get": [...] },
  "ops_extra": { ... }
};
```

---

## 已知限制

1. **单节点优先**：取第一个遇到的节点，多节点需扩展
2. **日志格式依赖**：`metrics_summary` 需包含 cycle 和 delta/total 字段
3. **内网 CDN**：需将 ECharts 下载到本地并修改 `script src`
4. **全零指标**：部分指标（如 master_ttl_*）在测试数据中全零，不渲染图表但会在报告中提示
5. **时间过滤边界**：同一 cycle 多个 part_index 合并后再过滤，部分 cycle 可能部分数据被过滤

---

## 关键代码参考

### 日志解析

```python
payload = json.loads(parts[7].strip())
cycle = payload['cycle']
for entry in payload['metrics']:
    name = entry['name']
    delta = entry['delta']   # {'count': N, 'p99': V, 'avg_us': V, 'max_us': V, 'p50': V, ...}
    total = entry['total']   # 同上
```

### 同 cycle 合并

```python
# latency 字段：非零优先
for f in ('p99', 'avg_us', 'max_us', 'p50', 'p90'):
    dv = delta.get(f, 0)
    odv = old_delta.get(f, 0)
    if dv == 0 and odv != 0:
        delta[f] = odv

# count 累加
delta['count'] = old_delta.get('count', 0) + delta.get('count', 0)

# total 取 max
old_total[f] = max(total.get(f, 0), old_total.get(f, 0))
```

### HTML 生成（string.Template 防冲突）

```python
from string import Template
tpl = Template(HTML_PAGE_TEMPLATE)  # CSS {} 用 {{}} 转义
html = tpl.safe_substitute(node='...', js_data='...', ...)
```

---

*文档版本: 2.0 | 日期: 2026-05-11 | 验证: 193 cycles → 53 cycles (--since 17:10), 45 metrics, 7 groups*
