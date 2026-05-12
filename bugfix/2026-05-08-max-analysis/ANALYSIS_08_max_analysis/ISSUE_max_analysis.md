# Issue: 最大延迟 Trace 深度分析 (8219us - 9506us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) + 业务错误 |
| **影响组件** | Worker1 (RPC Client) / Worker2 (RPC Server) / Master |
| **影响节点** | **192.168.219.74** (问题节点), 其他 Worker/Master |
| **严重程度** | **High** |
| **Trace ID** | max framework_us / max e2e_us |
| **数据包** | `a4f54526a1ba466e8fbd039240db0b90.gz` → 128 个 trace 文件 |

---

## 一、数据包概述

### 1.1 Trace 来源

- 压缩包: `a4f54526a1ba466e8fbd039240db0b90.gz`
- 解压后: `trace-1157/` 目录
- 文件数: **128 个** `.trace` 文件
- 时间范围: `2026-05-08 02:39:06` ~ `2026-05-08 02:46:27`
- 涉及的 Worker 节点:
  - `192.168.219.74` (问题节点，主要报错点)
  - `192.168.102.84`, `192.168.182.18`, `192.168.235.146` (Master 节点)
  - `192.168.210.142`, `192.168.199.148`, `192.168.42.81`, `192.168.210.194` (其他 Worker)

### 1.2 分析方法

沿用 `ANALYSIS_01` ~ `ANALYSIS_07` 的框架分解思路:

```
e2e = client_req + remote_processing + client_rsp
     = client_req + (server_req_q + server_exec + server_rsp_q + network_residual) + client_rsp
```

通过 `ZMQ_RPC_FRAMEWORK_SLOW` 日志提取各阶段延迟，结合错误日志 (`obj_cache_shm_unit.cpp:256`) 定位根因。

---

## 二、最大延迟 Trace 详细分析

### 2.1 Trace `0c4100d8` - framework_us=8219 (Remote Pull 失败)

**Framework 数据**:

```
framework_us=8219
  client_req_framework_us=4228       // ⚠️ 极高 (正常 <100us)
  remote_processing_us=3988
    server_req_queue_us=17           // ✅ 正常
    server_exec_us=18                // ✅ 正常
    server_rsp_queue_us=30           // ✅ 正常
    network_residual_us=3922         // ⚠️ 偏高
  client_rsp_framework_us=21         // ✅ 正常
e2e_us=8237
```

**时间线 (Worker1 192.168.219.74)**:

| 时间 | 事件 |
|------|------|
| 02:41:54.117293 | `[Get] Receive`, inflightRemoteGet: 1 |
| 02:41:54.117330 | Query metadata from master: 192.168.102.84:31402 |
| 02:41:54.121581 | **ZMQ_RPC_FRAMEWORK_SLOW** (client_req=4228us!) |
| 02:41:54.125589 | 第一个 ZMQ_RPC_FRAMEWORK_SLOW (汇总, client_req=4228) |
| 02:41:54.125646 | Master query done, cost: 8.322ms |
| 02:41:54.125662 | **Eviction start** |
| 02:41:54.125708 | **Evict is going on...** |
| 02:41:54.125766 | **Error: Shared memory no space in arena: 2** |
| 02:41:54.125771 | **Out of memory, get remote abort** |
| 02:41:54.125796 | BatchGetObjectFromRemoteOnLock failed |
| 02:41:54.127383 | TryGetObjectFromRemote failed |
| 02:41:54.127431 | `[Get] Done` |

**关键发现**:
- `client_req_framework_us=4228us` — 异常高，但不是 OOM 导致的内存分配等待
- Master 查询耗时 8.322ms（因为 Master 负载高或网络延迟）
- 随后触发 OOM，Remote Pull 失败

---

### 2.2 Trace `567b961e` - e2e_us=10162 (Remote Pull 成功)

**Framework 数据** (来自 Worker2 192.168.210.142 侧):

```
framework_us=9506
  client_req_framework_us=18         // ✅ 正常
  remote_processing_us=10133
    server_req_queue_us=36          // ✅ 正常
    server_exec_us=656              // ⚠️ 偏高 (数据读取)
    server_rsp_queue_us=4922         // ❌ 异常高 (瓶颈!)
    network_residual_us=4517         // ⚠️ 偏高
  client_rsp_framework_us=10
e2e_us=10162
```

**时间线**:

| 时间 | 节点 | 事件 |
|------|------|------|
| 02:45:53.973138 | Worker2 210.142 | Query metadata from master: 192.168.199.148 |
| 02:45:53.973451 | Worker2 210.142 | Master query done, cost: 0.320ms |
| 02:45:53.973469 | Worker2 210.142 | **[Get] Remote pull**, src=210.142, dst=219.74 |
| 02:45:53.983650 | Worker2 210.142 | **ZMQ_RPC_FRAMEWORK_SLOW** (server_rsp_q=4922us!) |
| 02:45:54.189653 | Worker1 219.74 | **[Get/RemotePull] Receive**, count: 1 |
| 02:45:54.189680 | Worker1 219.74 | **URMA write** (jetty id:1036, inflight:2) |

**关键发现**:
- Remote Pull **成功**完成（不同于其他 trace 的失败）
- `server_rsp_queue_us=4922us` — Worker1 侧响应排队异常高
- `network_residual_us=4517us` — URMA 传输本身偏慢
- `server_exec_us=656us` — Worker2 读取数据耗时（数据量大）

---

### 2.3 Trace `71a7512a` - framework_us=6582 (双阶段 OOM)

**Framework 数据**:

```
# 第一阶段 (Master RPC 完成)
framework_us=6582
  client_req_framework_us=5860       // ⚠️ 极高
  remote_processing_us=229
  ...

# 第二阶段 (最终汇总)
framework_us=3829
  client_req_framework_us=21         // ✅ 正常
  remote_processing_us=245
  client_rsp_framework_us=3599       // ❌ 异常高
  ...
```

**关键发现**:
- 两个阶段的 `ZMQ_RPC_FRAMEWORK_SLOW` 日志说明请求经过了两个处理周期
- 第一阶段 client_req 高是因为 Master 元数据查询慢（5860us）
- 第二阶段 client_rsp 高是因为 OOM 后处理延迟（3599us）

---

## 三、关键模式总结

### 3.1 所有 Trace 的共同模式

| 特征 | 发生率 | 说明 |
|------|--------|------|
| **OOM 错误** | **100%** (所有检查的 trace) | `Shared memory no space in arena: 2` |
| **问题节点** | 100% | `192.168.219.74` |
| **Eviction 触发** | 100% | `worker_oc_eviction_manager.cpp:421` |
| **Eviction 失败** | 高概率 | `failed size: 1222~1224` (几乎全部失败) |
| **Master RemoveMeta** | 100% | 对象被标记为 EVICTION timeout |

### 3.2 延迟分解

| 指标 | 正常范围 | 观测范围 | 瓶颈 |
|------|----------|----------|------|
| client_req_framework | < 100us | 13us - **5860us** | Master 查询 + Eviction 尝试 |
| server_req_queue | < 100us | 12us - 36us | ✅ 正常 |
| server_exec | < 100us | 18us - 656us | 数据读取 |
| server_rsp_queue | ≈ network | 17us - **4922us** | Worker1 响应瓶颈 |
| network_residual | < 10ms | 151us - 6028us | URMA 传输 |
| client_rsp_framework | < 100us | 8us - **5679us** | OOM 后处理 |

### 3.3 内存状态 (来自 Trace `d899f96a`)

```
total size limit:     12884901888  (12GB, Arena 上限)
total physical mem:   12855934976  (~12GB)
total real memory:    12855623808  (~12GB)
total memory usage:   10292974353  (~9.6GB)
try alloc size:       8388672      (8MB 对象)
cacheType:            0
```

**解读**: Arena 剩余空间不足，分配 8MB 对象失败。

---

## 四、根因分析

### 4.1 问题链路

```
外部 Client                  Worker1 (219.74)              Worker2/ Master
    │                        (RPC Client)                      │
    │------ Get Request ---->|                                │
    │                        │ 1. 查询 Master 元数据           │
    │                        │ 2. Master 返回对象位置          │
    │                        │ 3. 尝试分配共享内存 (8MB)        │
    │                        │    ❌ 失败: Arena 已满           │
    │                        │ 4. 触发 Eviction Manager        │
    │                        │    ❌ 1222 个对象全部 evict 失败  │
    │                        │ 5. Remote Pull 失败             │
    │                        │ 6. 删除 unacked meta            │
    │                        │ 7. RemoveMeta 到 Master         │
    │<------ Error ---------|                                │
```

### 4.2 根因链

1. **直接原因**: `Shared memory no space in arena: 2` — Worker1 (192.168.219.74) 共享内存 Arena 耗尽
2. **加剧因素**: Eviction 尝试失败 — 1222+ 对象全部 evict 失败，内存压力持续
3. **内存状态**: Arena 使用了 ~10GB/12GB，但无法回收（eviction 全部失败）
4. **影响**: 所有发往 192.168.219.74 的 Remote Pull 请求全部失败

### 4.3 两次 ZMQ_RPC_FRAMEWORK_SLOW 日志的原因

一些 trace（如 `71a7512a`, `2248d911`）出现**两次** `ZMQ_RPC_FRAMEWORK_SLOW`：

1. **第一次**: Master RPC (QueryMeta) 完成时记录，此时 client_req 高因为 Master 查询慢
2. **第二次**: 最终 Remote Pull 结果汇总

这说明框架在 Master RPC 和 Remote Pull 两个阶段分别做了耗时记录。

---

## 五、结论

| 问题 | 答案 |
|------|------|
| 最大延迟 trace 的瓶颈在哪？ | **client_req_framework (Master 查询 + OOM 处理)** 和 **server_rsp_queue (Worker1 响应)** |
| 根因是什么？ | Worker1 (192.168.219.74) 共享内存 Arena 耗尽，OOM 导致 Remote Pull 失败 |
| 为什么 eviction 失败？ | 内存压力持续，1222+ 对象全部 evict 失败 |
| 与之前的分析一致吗？ | **完全一致** — 与 `ANALYSIS_01_client_req_framework` 的根因相同（同一节点同一问题） |
| 有哪些新发现？ | `server_rsp_queue` 在成功完成的 Remote Pull 中也偏高（4922us），说明 Worker1 是系统瓶颈 |

---

## 六、建议

| 优先级 | 建议 | 预期效果 |
|--------|------|----------|
| **P0** | 扩容 Worker1 (192.168.219.74) 共享内存 Arena | 消除 OOM，接受更多 Remote Pull |
| **P0** | 调查 Eviction 为什么 100% 失败 | 释放已有内存，降低 Arena 压力 |
| **P1** | 优化 Worker1 的 server_rsp_queue 处理 | 减少 Remote Pull 响应延迟 |
| **P1** | 监控 `no space in arena: 2` 错误频率 | 提前预警，避免 OOM 影响 |

---

## 附录 A: 全量 Trace 列表 (部分)

| Trace ID | framework_us | client_req | remote_process | client_rsp | server_req_q | server_exec | server_rsp_q | network_res | e2e_us | 备注 |
|----------|-------------|------------|----------------|------------|--------------|-------------|--------------|------------|--------|------|
| 0c4100d8 | 8219 | 4228 | 3988 | 21 | 17 | 18 | 30 | 3922 | 8237 | OOM |
| 567b961e | 9506 | 18 | 10133 | 10 | 36 | 656 | 4922 | 4517 | 10162 | 成功但 rsp_q 高 |
| 71a7512a | 6582→3829 | 5860→21 | 229→245 | 517→3599 | 13→12 | 24→37 | 17→18 | 174→176 | 6607 | 双阶段 OOM |
| 2248d911 | 5930→3807 | 55→488 | 216→238 | 5679→3116 | 19→18 | 20→35 | 24→19 | 151→165 | 5951 | 双阶段 OOM |
| d899f96a | 5680 | 2907 | 2792 | 23 | 15 | 43 | 18 | 2716 | 5723 | OOM + 内存详情 |
| 153cead4 | 5361→3967 | 27→45 | 2210→3943 | 3154→17 | 16→18 | 31→38 | 28→17 | 2134→3868 | 5392 | 双阶段 OOM |
| a96f55e9 | 6097→3068 | 13→14 | 6096→3093 | 16→8 | 19→17 | 28→48 | 20→23 | 6028→3003 | 6126 | OOM |
| 58e00acf | 4114 | 40 | 502 | 3809 | 18 | 237 | 12 | 233 | 4352 | Eviction 失败详情 |

---

## 附录 B: 关键日志片段

### B.1 Arena 内存耗尽日志

```
arena.cpp:124 | total size limit:12884901888, total physical memory usage:12855934976,
total real memory usage:12855623808, total memory usage:10292974353,
try alloc size:8388672, cacheType:0
```

### B.2 Eviction 失败日志

```
EvictionList size before evict: 1222~1224
EvictionList size after evict: 1221~1224, failed size: 1221~1224  ← 几乎全部失败
```

### B.3 OOM 导致 Remote Pull 失败

```
obj_cache_shm_unit.cpp:256 | Error while allocating memory.
  Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]

worker_oc_service_batch_get_impl.cpp:389 | Out of memory, get remote abort.
worker_oc_service_batch_get_impl.cpp:204 | BatchGetObjectFromRemoteOnLock failed.
worker_oc_service_batch_get_impl.cpp:244 | Failed to get object data from remote.
```
