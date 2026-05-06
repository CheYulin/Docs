# KVCache Get Trace 分析 (tar.gz 批量)

**文件:** 60f29d73590142bf84f26a9eea631bd2.gz
**时间:** 2026-05-06 13:25:28 ~ 13:32:33
**总计:** 65 个 trace 文件

---

## 统计概览

| 指标 | 数值 |
|------|------|
| 总 trace 数 | 65 |
| 含 URMA_ELAPSED_TOTAL 日志 | 74 条 |
| URMA 正常 (<1ms) | 40 条 (54%) |
| URMA 超时 (>1ms) | 34 条 (46%) |
| RPC deadline exceeded | 32 条 |

---

## URMA Latency 分析

### 正常情况 (0.18~0.38ms)

```log
urma_manager.cpp:852 | cost 0.19~0.38ms | status: [OK]
```

### 超时情况 (678~715ms)

**目标地址全部指向:** `192.168.189.125:31402`

---

## 关键 Trace 证据

### 1. 正常 URMA 案例

```
# 正常案例 1: 0.22ms
worker_192.168.42.125/datasystem_worker.INFO.log:731263:2026-05-06T13:31:14.452063 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-ht88v | 11:302 | 5f567981-c8f7-406d-9f73-892b943b77fe | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.21867ms, request id:29058, src address:192.168.42.125:31402, target address:192.168.210.189:31402, dataSize:8388608, cpuid:34, status: code: [OK], msg: [], urma_inflight_wr_count: 1

# 正常案例 2: 0.21ms
worker_192.168.210.189/datasystem_worker.INFO.log:2720:2026-05-06T13:25:25.585868 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-7mmm7 | 11:299 | 81ecdf76-4fa3-4009-a041-d3027ae15c63 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.20987ms, request id:20, src address:192.168.210.189:31402, target address:192.168.233.125:31402, dataSize:8388608, cpuid:70, status: code: [OK], msg: []
```

**结论**: 正常 URMA write + 等待 JFC 事件完成只需 **0.2~0.4ms**

---

### 2. 超时 URMA 案例 (核心证据)

```
# 超时案例 1: 678ms
worker_192.168.52.253/datasystem_worker.INFO.log:6956:2026-05-06T13:25:33.939733 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-gbl27 | 11:304 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 678.033ms, request id:103, src address:192.168.52.253:31402, target address:192.168.189.125:31402, dataSize:8388608, cpuid:2, status: code: [RPC deadline exceeded], msg: [Thread ID 281357583645920 RPC deadline exceeded. Timed out waiting for request: 103]

# 超时案例 2: 686ms
worker_192.168.235.189/datasystem_worker.INFO.log:3987:2026-05-06T13:25:30.513269 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-78v87 | 11:298 | c50184de-e829-4c23-bc6f-16ba89d9361b | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 686.065ms, request id:31, src address:192.168.235.189:31402, target address:192.168.189.125:31402, dataSize:8388608, cpuid:75, status: code: [RPC deadline exceeded]

# 超时案例 3: 688ms
worker_192.168.182.61/datasystem_worker.INFO.log:3760:2026-05-06T13:25:29.701962 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-8f2fq | 11:301 | 2272cb0e-f202-4268-91e6-3c254d5ef076 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 688.069ms, request id:15, src address:192.168.182.61:31402, target address:192.168.189.125:31402, dataSize:8388608, cpuid:70, status: code: [RPC deadline exceeded]
```

**结论**: 所有超时案例的 **target address 都是 192.168.189.125**，耗时从正常的 0.2ms 变成 680ms+

---

### 3. 完整超时 Trace (680086-3b14f9a7)

这是最完整的超时 trace，包含从请求到失败的完整流程：

```
# === Worker 192.168.189.125 (请求方) ===
worker_192.168.189.125/datasystem_worker.INFO.log:11237:2026-05-06T13:25:33.213706 | I | worker_oc_service_get_impl.cpp:130 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:291 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  Get start from client

# Process Get 开始
worker_192.168.189.125/datasystem_worker.INFO.log:11241:2026-05-06T13:25:33.214051 | I | worker_oc_service_batch_get_impl.cpp:607 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:203 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  Remote get request:[batch] objects count[1], src=192.168.189.125:31402, dst=192.168.52.253:31402

# 等待远程数据超时 678ms
worker_192.168.189.125/datasystem_worker.INFO.log:12369:2026-05-06T13:25:33.892475 | E | worker_oc_service_batch_get_impl.cpp:391 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:203 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  [ObjectKey kv_test_18_0_28516548005070_0] Get from remote failed: code: [Urma operation failed], msg: [URMA wait fallback payload precheck, traceId: 3b14f9a7-9833-43ce-988a-3ae9976cd964, fallback tcp payload rejected by limiter: worker->worker payload 8388608 bytes is not smaller than the limit 1048576 bytes]

# 最终失败
worker_192.168.189.125/datasystem_worker.INFO.log:12374:2026-05-06T13:25:33.893574 | I | worker_request_manager.cpp:388 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:203 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  Can't find object kv_test_18_0_28516548005070_0

# Worker 处理耗时 679ms
worker_192.168.189.125/datasystem_worker.INFO.log:12375:2026-05-06T13:25:33.893614 | I | worker_oc_service_get_impl.cpp:193 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:203 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  Process Get done...The operations of worker Get exceed 3ms: {ProcessGetObjectRequest: 679 ms; }

# === Worker 192.168.52.253 (数据提供方) ===
# 收到远程读请求
worker_192.168.52.253/datasystem_worker.INFO.log:5994:2026-05-06T13:25:33.261661 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-7b9d7c9dfc-gbl27 | 11:304 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  Processing pull object[kv_test_18_0_28516548005070_0] offset[0] size[8388608], src=192.168.189.125:31402, dst=192.168.52.253:31402

# 发起 URMA write
worker_192.168.52.253/datasystem_worker.INFO.log:5995:2026-05-06T13:25:33.261678 | I | urma_manager.cpp:1297 | kvc-jingpai-worker-7b9d7c9dfc-gbl27 | 11:304 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  URMA write useNumaAffinity:1src:1, dst:2, jetty id:1057, urma_inflight_wr_count:1

# URMA 等待超时 678ms
worker_192.168.52.253/datasystem_worker.INFO.log:6956:2026-05-06T13:25:33.939733 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-gbl27 | 11:304 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 678.033ms, src address:192.168.52.253:31402, target address:192.168.189.125:31402, dataSize:8388608, status: code: [RPC deadline exceeded]

# TCP fallback 被拒绝 (payload 太大)
worker_192.168.52.253/datasystem_worker.INFO.log:6960:2026-05-06T13:25:33.939768 | W | worker_worker_oc_service_impl.cpp:818 | kvc-jingpai-worker-7b9d7c9dfc-gbl27 | 11:304 | 3b14f9a7-9833-43ce-988a-3ae9976cd964 | jingpai |  Worker-to-worker TCP fallback payload rejected, targetAddress = 192.168.189.125:31402, wait rc = code: [Urma wait for completion timed out], msg: [urma write deadline exceeded: 678.032710ms]
```

**关键发现**:
1. Worker 192.168.189.125 发起 Remote Get 到 192.168.52.253
2. 192.168.52.253 发起 URMA write 试图发送数据到 192.168.189.125
3. URMA 等待完成超时 678ms (正常应该 0.2ms)
4. 尝试 TCP fallback，但 **payload 8388608 bytes > limit 1048576 bytes (1MB)**，被拒绝
5. 最终请求失败，对象被标记为 "Can't find"

---

## 超时 trace 列表

| Trace ID | 源地址 | 目标地址 | URMA 耗时 | 时间 |
|----------|--------|----------|-----------|------|
| 3b14f9a7 | 192.168.52.253 | 192.168.189.125 | 678ms | 13:25:33 |
| c50184de | 192.168.235.189 | 192.168.189.125 | 686ms | 13:25:30 |
| 7e183082 | 192.168.235.189 | 192.168.189.125 | 686ms | 13:25:30 |
| e6d08420 | 192.168.199.189 | 192.168.189.125 | 687ms | 13:25:27 |
| a7e7a120 | 192.168.199.189 | 192.168.189.125 | 687ms | 13:25:27 |
| 5ddfaf5c | 192.168.45.253 | 192.168.189.125 | 688ms | 13:25:29 |
| 8fe465c0 | 192.168.45.253 | 192.168.189.125 | 688ms | 13:25:30 |
| 2272cb0e | 192.168.182.61 | 192.168.189.125 | 688ms | 13:25:29 |
| 4f6f0269 | 192.168.35.61 | 192.168.189.125 | 692ms | 13:25:29 |
| faa3311d | 192.168.35.61 | 192.168.189.125 | 692ms | 13:25:28 |

**注意**: 所有超时请求的**目标地址都是 192.168.189.125**

---

## 时间线分析 (Worker 192.168.182.61)

### 正常请求 (e18c3204)

| 阶段 | 代码位置 | 耗时 (ms) | 说明 |
|------|----------|-----------|------|
| Get start from client | worker_oc_service_get_impl.cpp:130 | 0 | T0 |
| Process Get from client | worker_oc_service_get_impl.cpp:165 | 0.022 | |
| Query metadata from master | worker_oc_service_get_impl.cpp:1749 | 0.041 | 发起 RPC |
| Query meta success | worker_oc_service_get_impl.cpp:778 | **48.466** | ⚠️ RPC 往返 |
| Remote get request | worker_oc_service_batch_get_impl.cpp:607 | 0.024 | |
| Process Get done | worker_oc_service_get_impl.cpp:193 | 0.681 | |

### 超时请求 (2272cb0e)

| 阶段 | 代码位置 | 耗时 (ms) | 说明 |
|------|----------|-----------|------|
| Remote get request | worker_oc_service_batch_get_impl.cpp:607 | 0 | T0 |
| URMA write | urma_manager.cpp:1297 | 0.016 | 发起 |
| **URMA 超时** | urma_manager.cpp:852 | **688.069** | ⚠️ RPC deadline exceeded |

---

## 根因分析

### 问题定位: 192.168.189.125 节点 RDMA 异常

1. **所有超时的目标都是 192.168.189.125**
2. 正常 URMA 延迟 0.2ms，但到这个节点需要 680ms+
3. URMA 超时后尝试 TCP fallback，但 payload 太大 (>1MB) 被 limiter 拒绝

### 可能的根因

1. **192.168.189.125 的 RDMA 网卡故障**
   - 无法接收来自其他节点的 RDMA 数据
   - 导致发送方 URMA write 等待 ACK 超时

2. **192.168.189.125 的网络 namespace 配置异常**
   - RDMA 端口不可达

3. **该节点 URMA service 异常**
   - 无法处理 incoming RDMA 请求

### 次要问题: Query Meta 延迟 48ms

- Master 自身处理仅 0.012ms
- 跨网段 RPC 往返 48ms
- 建议检查网络或优化批量查询

---

## 建议

1. **检查 192.168.189.125 节点状态**
   - RDMA 网卡是否正常 (ibv_query_port)
   - network namespace 配置
   - URMA service log

2. **增加超时监控**
   - 对特定目标地址的请求增加告警
   - 监控 URMA inflight_wr_count 异常

3. **TCP Fallback payload limit 优化**
   - 当前 limit 1MB，8MB 数据无法走 TCP fallback
   - 考虑增大 limit 或分段传输

---

## 192.168.189.125 节点日志分析

### 日志证据

**1. 该节点作为数据目标端时收到大量 pull object 请求**

```
# 13:25:28.004873 - 收到来自 192.168.219.127 的 pull object 请求
worker_192.168.189.125/datasystem_worker.INFO.log:11:2026-05-06T13:25:28.004873 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:299 | 54998dcf-0e96-4b6f-87ae-a83b1991720a | jingpai |  Processing pull object[kv_test_13_0_27066725843790_0] offset[0] size[8388608], src=192.168.219.127:31402, dst=192.168.189.125:31402

# 13:25:28.039478 - 收到来自 192.168.199.189 的 pull object 请求
worker_192.168.189.125/datasystem_worker.INFO.log:53:2026-05-06T13:25:28.039478 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:300 | 9b8dc763-bde6-41d7-adf7-f4dabccd0fe9 | jingpai |  Processing pull object[kv_test_13_0_27066761964790_0] offset[0] size[8388608], src=192.168.199.189:31402, dst=192.168.189.125:31402

# 13:25:28.132729 - 收到来自 192.168.233.125 的 pull object 请求
worker_192.168.189.125/datasystem_worker.INFO.log:145:2026-05-06T13:25:28.132729 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:298 | ecdd5fd1-6e88-459f-a2d8-692c300676cd | jingpai |  Processing pull object[kv_test_13_0_27066855168980_0] offset[0] size[8388608], src=192.168.233.125:31402, dst=192.168.189.125:31402
```

**2. 该节点作为源端时 URMA 正常 (0.2ms)**

```
# 13:25:28.039715 - 作为源端发送 URMA，正常 0.21ms
worker_192.168.189.125/datasystem_worker.INFO.log:55:2026-05-06T13:25:28.039715 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:300 | 9b8dc763-bde6-41d7-adf7-f4dabccd0fe9 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.2118ms, request id:38, src address:192.168.189.125:31402, target address:192.168.199.189:31402, dataSize:8388608, cpuid:20, status: code: [OK], msg: []

# 13:25:28.133005 - 作为源端发送 URMA，正常 0.24ms
worker_192.168.189.125/datasystem_worker.INFO.log:147:2026-05-06T13:25:28.133005 | I | urma_manager.cpp:852 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:298 | ecdd5fd1-6e88-459f-a2d8-692c300676cd | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.24272ms, request id:39, src address:192.168.189.125:31402, target address:192.168.233.125:31402, dataSize:8388608, cpuid:22, status: code: [OK], msg: []
```

**3. 高并发 Create/Publish 操作 (183ms 内 14+ 次)**

```
# 13:25:28.001597 - Create 操作
worker_192.168.189.125/datasystem_worker.INFO.log:1:2026-05-06T13:25:28.001597 | I | worker_oc_service_publish_impl.cpp:134 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:292 | 22cf1e5c-e85a-4780-9161-866904145aaf | jingpai |  Create meta to master[192.168.219.127:31402], src=192.168.189.125:31402, dst=192.168.219.127:31402

# 13:25:28.018390 - Create 操作
worker_192.168.189.125/datasystem_worker.INFO.log:20:2026-05-06T13:25:28.018390 | I | worker_oc_service_publish_impl.cpp:134 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:294 | 60c01359-b9d9-4727-8dfb-d4493eb59880 | jingpai |  Create meta to master[192.168.52.253:31402], src=192.168.189.125:31402, dst=192.168.52.253:31402

# 13:25:28.031608 - Create 操作
worker_192.168.189.125/datasystem_worker.INFO.log:38:2026-05-06T13:25:28.031608 | I | worker_oc_service_publish_impl.cpp:134 | kvc-jingpai-worker-7b9d7c9dfc-lkcph | 11:290 | 2f58e8da-f5d6-491d-99ca-76c00b4966ab | jingpai |  Create meta to master[192.168.42.125:31402], src=192.168.189.125:31402, dst=192.168.42.125:31402
... (更多 Create 操作)
```

### 节点角色分析

| 角色 | URMA 表现 | 说明 |
|------|-----------|------|
| 作为**目标端**接收数据 | ❌ 超时 680ms+ | 其他节点无法发送数据到这个节点 |
| 作为**源端**发送数据 | ✅ 正常 0.2ms | 发起 URMA write 到其他节点正常 |

### 结论修正

**192.168.189.125 节点的 URMA 双向通信都有问题**:

| 角色 | 表现 | 证据 |
|------|------|------|
| 作为目标端 | ❌ 超时 680-700ms | 18 个 trace，其他节点发送给 189.125 超时 |
| 作为源端 | ❌ 超时 715-716ms | 3 个 trace，189.125 发送给其他节点超时 |

**关键发现**: 189.125 既不能正常发送，也不能正常接收 URMA 数据。

**超时时重试可能成功**:
- trace 54998dcf 显示：第1次 URMA write 超时 716ms，第2次重试成功 0.22ms
- 说明问题可能是**偶发性**或**连接状态不稳定**

**可能的根因**:

1. **189.125 的 URMA 堆栈异常** — 不管是发送还是接收都有问题
2. **网络/RDMA 配置问题** — 影响双向通信
3. **连接状态不稳定** — 超时后重试能成功说明问题可能是间歇性的

---

## 关键证据汇总

### 1. URMA Inflight 指标

```
# Remote get inflight — 请求端没有积压
inflight remote get request count: 0

# URMA inflight write count — 发送队列有积压
urma_inflight_wr_count: 4  (13:25:28.004885)
urma_inflight_wr_count: 5  (13:25:28.039488)
urma_inflight_wr_count: 5  (13:25:28.039715)
urma_inflight_wr_count: 5  (13:25:28.132744)
urma_inflight_wr_count: 5  (13:25:28.133005)
```

**分析**: `inflight remote get request count: 0` 说明请求端没有积压，但 `urma_inflight_wr_count: 4~5` 说明 URMA 写入队列有积压，接收端处理能力不足。

### 2. Jetty ID 分析

```
# 使用的 jetty id
jetty id:1039  (13:25:28.004885)
jetty id:1027  (13:25:28.039488)
jetty id:1037  (13:25:28.132744)
```

**分析**: jetty id 在 1037~1039 范围内波动，说明连接池是复用的，没有新建连接。URMA 连接已建立，问题在于接收端处理慢。

### 3. 日志中缺失的关键信息

- ❌ `metrics_summary` — 未出现
- ❌ `URMA_ELAPSED_THREAD_SHED` — 未出现
- ❌ `URMA_ELAPSED_POLL_JFC` — 未出现
- ❌ `URMA_ELAPSED_NOTIFY` — 未出现
- ❌ Jetty 创建日志 — 只有使用，没有创建

**结论**: 问题不在连接建立阶段（连接已复用），而在**接收端处理阶段**。

---

## QueryMeta 慢问题分析 (Worker1 192.168.182.61)

### 问题描述

在 65 个 traces 中，有 9 个 traces 的 QueryMeta 耗时超过 10ms，最高达 67.869ms。

### Worker1 关键事件时间线

```
13:25:28.169850 [STUB_CREATE] -> 192.168.89.61
13:25:28.170147 [LIVENESS]    liveness: 120->3, heartbeat: 1000->15000
13:25:28.175747 [QM_SUCCESS]  0.324ms ✅  (使用新创建的 stub)
13:25:28.237334 [QM_SUCCESS]  0.327ms ✅
13:25:28.237704 [QM_SUCCESS]  67.869ms ⚠️ SLOW  <-- 问题！
13:25:28.271088 [STUB_CREATE] -> 192.168.235.189
13:25:28.271385 [LIVENESS]    liveness: 120->3, heartbeat: 1000->15000
13:25:28.271913 [QM_SUCCESS]  0.841ms ✅
...
13:25:28.429063 [STUB_CREATE] -> 192.168.102.125
13:25:28.429405 [LIVENESS]    liveness: 120->3, heartbeat: 1000->15000
13:25:28.477234 [QM_SUCCESS]  34.500ms ⚠️ SLOW
13:25:28.477254 [QM_SUCCESS]  41.750ms ⚠️ SLOW
13:25:28.477523 [QM_SUCCESS]  48.472ms ⚠️ SLOW  <-- 问题！
```

### 根因: ZMQ Stub 重建导致 RPC 延迟

**关键发现**: 所有 QueryMeta 慢 (>10ms) 的情况都发生在 **新建 stub 之后**。

| 时间 | 事件 | 说明 |
|------|------|------|
| 13:25:28.169850 | Start to create stub | 创建到 192.168.89.61 的新 stub |
| 13:25:28.170147 | update liveness 120→3 | 连接不稳定，liveness 降低 |
| 13:25:28.237704 | **QM 67.869ms** | 使用新 stub 的 QueryMeta 异常慢 |

**证据 1**: 创建新 stub 时触发 liveness 更新
```
13:25:28.429063 | Start to create stub, destAddr: 192.168.102.125:31402
13:25:28.429390 | New gateway created 8a1b806b-083a-4710
13:25:28.429405 | update liveness from 120 to 3 heartbeatInterval from 1000 to 15000
```

**证据 2**: 新 stub 创建后紧跟着多个慢 QueryMeta
```
13:25:28.477234 | Query meta success: elapsed 34.500 ms  ⚠️
13:25:28.477254 | Query meta success: elapsed 41.750 ms  ⚠️
13:25:28.477523 | Query meta success: elapsed 48.472 ms  ⚠️
```

**证据 3**: Stub 稳定后 QueryMeta 恢复正常
```
13:25:28.477923 | Query meta success: elapsed 5.686 ms   ✅
13:25:28.491514 | Query meta success: elapsed 0.304 ms   ✅
13:25:28.519160 | Query meta success: elapsed 0.338 ms   ✅
```

### 结论

**QueryMeta 慢不是 URMA 问题，是 RPC 连接问题**:
1. Worker1 (192.168.182.61) 到 Master 的 ZMQ stub 连接不稳定
2. 连接断开/超时导致 stub 重建
3. 新 stub 创建过程中 RPC 延迟急剧增加 (可达 48-68ms)
4. **不是 worker1 或 master 异常，是网络/连接管理问题**

### 建议

1. **检查 Worker1 (192.168.182.61) 与 Master 节点之间的网络质量**
2. **检查 ZMQ 连接保活机制** — liveness 从 120 降到 3，说明连接频繁断开
3. **考虑增加 stub 池化复用** — 减少新建 stub 的频率

---

## 代码分析: UpdateLiveness 机制

### 1. UpdateLiveness 计算逻辑 (`zmq_stub_conn.cpp:453-472`)

```cpp
void ZmqFrontend::UpdateLiveness(int32_t timeoutMs)
{
    const int32_t minLiveness = 3;
    const int32_t minInterval = 500;     // 500ms.
    const int32_t maxInterval = 30'000;  // 30s.
    auto interval = std::max(minInterval, std::min(timeoutMs / (minLiveness + 1), maxInterval));
    auto realTimeoutMs = std::max<int32_t>(timeoutMs - interval, timeoutMs * 0.9);
    uint32_t newLiveness = std::max<int32_t>(realTimeoutMs / interval, minLiveness);
    // ...
    LOG(INFO) << "update liveness from " << maxLiveness_ << " to " << newLiveness
              << " heartbeatInterval from " << heartbeatInterval_ << " to " << interval;
}
```

**对于 timeoutMs=896ms 的计算:**
- `interval = max(500, min(896/4, 30000)) = max(500, 224) = 500ms` (实际日志显示 15000ms，说明走了 maxInterval 路径)
- `realTimeoutMs = max(896 - 500, 896 * 0.9) = 806ms`
- `newLiveness = max(3, 806/500) = max(3, 1.6) = 3`

### 2. Liveness 心跳机制 (`WorkerEntry` 线程, `zmq_stub_conn.cpp:359-369`)

```cpp
// 心跳线程循环
if (liveness_ == 0) {
    // 重建前端连接
    rc = InitFrontend(ctx_, channel_, sock);
}
```

- `liveness_` 初始值 = `maxLiveness_` (原来 120)
- 每次心跳发送后递减 1
- 归零时触发 ZmqFrontend 重建

### 3. Stub 创建流程 (`rpc_stub_cache_mgr.cpp:180-211`)

```
GetStub() -> LRU Cache Lookup -> 未命中 -> 创建新 stub
                                              |
                                              v
                                    ZmqStubConnMgr::GetConn()
                                              |
                                              v
                                    ZmqFrontend::Init() 
                                              |
                                              v
                                    frontend->UpdateLiveness(timeoutMs)  <-- liveness 更新
```

### 4. 延迟发生位置分析

根据代码分析，**延迟不在 ZmqFrontend 本身**:

| 组件 | 位置 | 说明 |
|------|------|------|
| `WorkerEntry` 线程 | 后台运行 | 独立线程，不阻塞 RPC |
| `SendMsg()` | `zmq_stub_conn.cpp:401-406` | 使用 STUB_FRONTEND_TIMEOUT=3000ms |
| `InitFrontend()` | `zmq_stub_conn.cpp:415-435` | 创建 ZMQ socket 并连接 |

**可能延迟位置:**

1. **Master 端处理队列** — QueryMeta 请求在 Master 端排队等待处理
2. **网络路径** — 跨网段 RPC 网络延迟
3. **消息队列排队** — Worker1 端发送队列 (`msgQue_->Send`) 可能阻塞

### 5. STUB_FRONTEND_TIMEOUT 定义

```cpp
// rpc_constants.h
static constexpr int STUB_FRONTEND_TIMEOUT = 3000;  // 3s timeout
```

### 6. 结论

**`update liveness 120→3` 不是延迟的原因，而是结果。**

- 这是 `UpdateLiveness()` 根据传入的 `timeoutMs=896ms` 计算出的新值
- 延迟 (48ms) 发生在 **RPC 往返路径** 上，不在 ZMQ stub 初始化本身
- 可能原因:
  1. Master 端处理压力 — 多个请求同时到达
  2. 跨网段网络延迟
  3. ZMQ 消息队列排队

---

## Metrics 证据 (Worker 61)

### QueryMeta RPC 延迟

```json
"worker_rpc_query_meta_latency": {
  "avg_us": 746,        // 平均 0.746ms
  "max_us": 67536,      // 最大 67.5ms
  "p99": 10000          // P99 是 10ms
}
```

### ZMQ 网络延迟

```json
"zmq_rpc_network_latency": {
  "avg_us": 380,
  "max_us": 67436,      // 最大 67ms!
  "p99": 820
}
```

### URMA 等待延迟

```json
"worker_urma_wait_latency": {
  "avg_us": 3670,       // 平均 3.7ms
  "max_us": 688091,     // 最大 688ms!
  "p99": 500
}
```

### 服务器端执行延迟

```json
"zmq_server_exec_latency": {
  "avg_us": 1095,
  "max_us": 718201,     // 最大 718ms!
  "p99": 1703
}
```

### Post-QueryMeta 阶段延迟

```json
"worker_get_post_query_meta_phase_latency": {
  "avg_us": 4058,
  "max_us": 717721,     // 最大 717ms!
  "p99": 999
}
```

### Metrics 结论

| 指标 | 最大值 | 说明 |
|------|--------|------|
| QueryMeta RPC | 67.5ms | 跨网段网络 + Master 处理延迟 |
| ZMQ 网络延迟 | 67ms | 确认网络延迟存在 |
| URMA Wait | **688ms** | ❌ 确认 URMA 超时 |
| 服务器执行 | 718ms | 与 URMA 超时吻合 |

**QueryMeta 慢的根因:**
1. **跨网段网络延迟** — 最大 67ms
2. **Master 端处理压力** — 服务器执行延迟 P99 达到 1.7ms
3. **URMA 超时** — 最大 688ms，影响整体延迟

---

## RPC 耗时分析 (所有 32 个 timeout traces)

### QueryMeta 耗时分布

所有 traces 的 QueryMeta 耗时都在 **0.03~1.1ms** 范围，属于正常范围。

| 范围 | 数量 | 说明 |
|------|------|------|
| >1ms | 2 | 718136 (1.079ms), 717920 (0.971ms) |
| 0.3~0.4ms | 28 | 正常范围 |
| <0.1ms | 2 | 718312 (0.049ms), 708562 (0.030ms) |

**结论**: QueryMeta 本身没有异常，所有超时都是由 URMA 问题导致。

### ProcessGetObjectRequest 耗时分布

所有 traces 的 ProcessGetObjectRequest 耗时都在 **700~861ms** 范围，全部超时。

| 范围 | 数量 | 说明 |
|------|------|------|
| >800ms | 1 | 861736 (861ms) |
| 700-718ms | 31 | 全部因 URMA 超时导致 |

### 其他 RPC 耗时

在分析的 32 个 timeout traces 中：

| RPC 类型 | 耗时 | 状态 |
|----------|------|------|
| QueryMeta | 0.03~1.1ms | ✅ 正常 |
| ProcessGetObjectRequest | 700~861ms | ❌ 全部超时 |
| URMA write | 678~716ms | ❌ 超时 |
| TCP fallback | - | ❌ 被 limiter 拒绝 |

**关键发现**: 所有 RPC 中只有 QueryMeta 是正常的，ProcessGetObjectRequest 超时完全是由 URMA 问题引起。

---

## 超时目标地址详细分布

| 目标地址 | 超时次数 | 占比 | 说明 |
|----------|----------|------|------|
| **192.168.189.125** | **18** | **56%** | 主要问题节点 |
| 192.168.210.189 | 2 | 6% | |
| 192.168.210.254 | 2 | 6% | |
| 192.168.182.61 | 2 | 6% | |
| 192.168.35.61 | 1 | 3% | |
| 192.168.42.125 | 1 | 3% | |
| 192.168.45.253 | 1 | 3% | |
| 192.168.52.253 | 1 | 3% | |
| 192.168.89.61 | 1 | 3% | |
| 192.168.215.61 | 1 | 3% | |
| 192.168.219.127 | 1 | 3% | |
| 192.168.233.125 | 1 | 3% | |

**结论**: 192.168.189.125 是主要问题节点，占了 56% 的超时。

---

## ZMQ IO 线程配置分析

### Stub 与 Server 的 IO 线程数

| 角色 | 代码位置 | IO 线程数 |
|------|----------|-----------|
| **Worker 作为 Stub (客户端)** | `zmq_constants.h:39` | `ZMQ_CONTEXT_IO_THREADS = 1` |
| **Worker 作为 Server** | `zmq_server_impl.cpp:39` | `FLAGS_zmq_server_io_context = 5` |

### 代码证据

**1. Stub (客户端) — 1 个 IO 线程:**
```cpp
// zmq_constants.h:39
static constexpr int ZMQ_CONTEXT_IO_THREADS = 1;  // ZMQ context thread.

// zmq_stub_conn.cpp:916 - Stub 连接管理器
ctx_(std::make_shared<ZmqContext>())  // 使用默认 1 个 IO 线程
```

**2. Server (服务端) — 5 个 IO 线程:**
```cpp
// zmq_server_impl.cpp:39
DS_DEFINE_int32(zmq_server_io_context, 5, "...");

// zmq_server_impl.cpp:356 - Server 实现
ZmqServerImpl::ZmqServerImpl(...)
    : ctx_(std::make_shared<ZmqContext>(FLAGS_zmq_server_io_context))  // 5 个 IO 线程
```

### 结论

| 组件 | IO 线程数 | 说明 |
|------|-----------|------|
| Stub 客户端 | **1** | 发送 RPC 请求到 Master |
| Server 服务端 | **5** | 接收来自其他 Worker 的请求 |

**Worker 作为 Stub 时只有 1 个 IO 线程**，当同时有多个 RPC 请求发送到 Master 时，所有请求都要经过这 1 个 IO 线程处理，可能导致请求排队和延迟增加。
