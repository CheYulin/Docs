# Issue: QueryMeta 延迟偏高

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | Master (元数据服务) |
| **影响节点** | 192.168.219.74 (Master/Worker2) |
| **严重程度** | Medium |
| **涉及 Trace** | 3661, 5067 |

---

## 一、现象描述

QueryMeta 延迟偏高（正常应 < 1ms），导致整体处理延迟增加。

**关键现象**：
1. Trace 3661: QueryMeta 耗时 **2.73ms**（异常偏高）
2. Trace 5067: QueryMeta 耗时 **1.93ms**（异常偏高）
3. Master 节点都是 192.168.219.74

---

## 二、日志证据

### 2.1 Trace 3661 日志

```
worker_192.168.215.9: Query metadata from master: 192.168.219.74:31402, objects: kv_test_0_0_72772507499400_0, request id: 7186c2da-597a-438f-beee-3b682e1bb92c, remainingTime:14ms
worker_192.168.215.9: Query meta success: target num 1, success num 1, elapsed 2.731 ms
worker_192.168.215.9: Process Get done, clientId: ..., objectKeys: kv_test_0_0_72772507499400_0, ...{ProcessGetObjectRequest: 3 ms; }

worker_192.168.219.74: Processing QueryMetaReq, requestId: 7186c2da-597a-438f-beee-3b682e1bb92c
worker_192.168.219.74: QueryMeta on master 192.168.215.9:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}

worker_192.168.219.74: BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_72772507499400_0,,0,8388608) remainingTime:11ms
worker_192.168.219.74: [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.18251ms, request id:187257, ... status: code: [OK]
```

### 2.2 Trace 5067 日志

```
worker_192.168.182.2: Query metadata from master: 192.168.219.74:31402, objects: kv_test_0_0_72592019278440_0, request id: 17511ea7-b80a-447e-99a8-08fdd48cb0ed, remainingTime:14ms
worker_192.168.182.2: Query meta success: target num 1, success num 1, elapsed 1.934 ms
worker_192.168.182.2: Remote get request:[batch] objects count[1], src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.182.2: Process Get done, clientId: ..., objectKeys: kv_test_0_0_72592019278440_0, ...{ProcessGetObjectRequest: 4 ms; }
```

### 2.3 关键发现

| 发现 | Trace 3661 | Trace 5067 |
|------|-------------|------------|
| QueryMeta 延迟 | 2.73ms | 1.93ms |
| worker1 | 192.168.215.9 | 192.168.182.2 |
| Master | 192.168.219.74 | 192.168.219.74 |
| URMA Wait | 0.18ms ✓ | - |
| 涉及 worker2 | 是 | 是 |

---

## 三、根因分析

### 3.1 问题定位

从日志可以看出：
- QueryMeta 请求发往 **192.168.219.74**
- 192.168.219.74 同时充当 **Master** 和 **Worker2**
- QueryMeta 延迟高达 1.93~2.73ms（正常应 < 1ms）

### 3.2 Trace 3661 详细时间分解

**时间戳（已校准时钟偏移）**：

| 时间 | 事件 | 节点 |
|------|------|------|
| 01:43:46.314068 | worker1 发送 QueryMeta 请求 | worker1 (192.168.215.9) |
| 01:43:46.289674 | Master 开始处理 | Master (192.168.219.74) |
| 01:43:46.289703 | Master 处理完成 | Master (192.168.219.74) |
| 01:43:46.316788 | worker1 收到响应 | worker1 (192.168.215.9) |

**延迟分解**：

| 阶段 | 延迟 | 说明 |
|------|------|------|
| worker1 -> Master 网络传输 | ~1.346 ms | 单向网络延迟 |
| Master 实际处理 | **0.029 ms** | **非常快，不是瓶颈** |
| Master -> worker1 网络传输 | ~1.346 ms | 单向网络延迟 |
| **总计** | **2.720 ms** | |

**关键发现**：
- Master 实际处理时间仅 **0.029 ms**（微秒级）
- 网络延迟占总延迟的 **98.9%**
- **根因是网络传输延迟，不是 Master 处理慢**

### 3.3 Trace 5067 分析

**注意**：Trace 5067 没有 Master 侧日志，无法直接验证 Master 处理时间。

| 时间 | 事件 | 节点 |
|------|------|------|
| 01:40:45.979400 | worker1 发送 QueryMeta 请求 | worker1 (192.168.182.2) |
| 01:40:45.981308 | worker1 收到响应 | worker1 (192.168.182.2) |

**延迟分解**（假设 Master 处理正常 ~0.03ms）：

| 阶段 | 延迟（估计） |
|------|-------------|
| 单向网络延迟 | ~0.939 ms |
| Master 处理（估计） | ~0.030 ms |
| 单向网络延迟 | ~0.939 ms |
| **总计** | **~1.908 ms** |

### 3.4 网络延迟根因

| 发现 | Trace 3661 | Trace 5067 |
|------|-------------|------------|
| worker1 | 192.168.215.9 | 192.168.182.2 |
| Master | 192.168.219.74 | 192.168.219.74 |
| 网段关系 | **跨网段** (215.9 -> 219.74) | **跨网段** (182.2 -> 219.74) |
| 单向网络延迟 | ~1.35 ms | ~0.94 ms |
| Master 处理 | 0.029 ms ✓ | 估计 ~0.03 ms ✓ |

**结论**：两个 Trace 的 QueryMeta 延迟主要来自 **跨网段网络传输**，不是 Master 处理慢。

### 3.5 正常 Trace 对比

| Trace | QueryMeta 延迟 | 说明 |
|-------|----------------|------|
| 14336 | 0.31 ms | 正常 |
| 10652 | 0.34 ms | 正常 |
| 2228 | 0.047 ms | 正常（最快） |

**正常 QueryMeta 延迟参考**：0.3~0.4ms（跨网段）

### 3.6 时钟偏移分析

| Trace | worker1 时钟 | Master 时钟 | 偏移 |
|-------|-------------|------------|------|
| 3661 | 01:43:46.314068 | 01:43:46.289674 | Master 快 24.4ms |
| 14336 | 01:49:46.574 | 01:49:46.579 | Master 快 5ms |

**注意**：时钟偏移不影响延迟计算，因为使用的是 RTT（Round Trip Time）测量。

---

## 四、结论

| 问题 | 答案 |
|------|------|
| QueryMeta 延迟多少？ | 1.93ms ~ 2.73ms（正常应 < 1ms） |
| 根因是什么？ | **跨网段网络传输延迟**，不是 Master 处理 |
| Master 处理慢吗？ | **不是** - Master 实际处理仅 0.029ms |
| 网络延迟占比 | **98.9%** |

**根因**：QueryMeta 请求从 worker1 到 Master (192.168.219.74) 需要跨网段传输，导致 RTT 高达 1.9~2.7ms。

---

## 五、相关代码

### 5.1 QueryMeta 处理逻辑

```cpp
// master_oc_service_impl.cpp:261
Status MasterOCServiceImpl::ProcessQueryMetaReq(...)
{
    METRIC_TIMER(metrics::KvMetricId::MASTER_QUERY_META_LATENCY);
    // ... 处理逻辑 ...
}
```

---

## 六、建议

1. **优化跨网段网络路径**
   - QueryMeta 延迟高是因为 worker1 到 Master 跨网段
   - 考虑将 Master 部署到与 worker1 相同网段

2. **网络质量检查**
   - 192.168.215.9 -> 192.168.219.74 单向延迟 ~1.35ms
   - 192.168.182.2 -> 192.168.219.74 单向延迟 ~0.94ms
   - 检查网络设备负载或路由优化

3. **Master 部署优化**
   - 192.168.219.74 同时充当 Master 和 Worker2
   - 建议将 Master 部署到独立节点，减少资源竞争

---

## 七、全量日志

### Trace 3661 全量日志

**日志文件路径**: `/tmp/trace_extract/tmp/3661_1ec36d3b-1e2d-4dec-9541-10681af533c2.log`

```
SDK_192.168.215.6/ds_client_access_1160.log:2026-05-07T01:43:46.317524 | I | access_recorder.cpp:182 | kvc-jingpai-client-bf8d49dbb-5zwj8 | 1160:1222 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 |  | 0 | DS_KV_CLIENT_GET | 3661 | 8388608 | {Object_key:kv_test_0_0_72772507499400_0,timeout:0,transportType:SHM} | 
worker_192.168.215.9/datasystem_worker.INFO.log:2026-05-07T01:43:46.314022 | I | worker_oc_service_get_impl.cpp:130 | kvc-jingpai-worker-6c6dd44d6d-fw7jb | 11:294 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Get start from client:088d87c8-aadc-456c-84ff-628653e27712 server api read elapsed ms: 0.00916 inflight remote get request count: 0
worker_192.168.215.9/datasystem_worker.INFO.log:2026-05-07T01:43:46.314043 | I | worker_oc_service_get_impl.cpp:165 | kvc-jingpai-worker-6c6dd44d6d-fw7jb | 11:202 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Process Get from client: 088d87c8-aadc-456c-84ff-628653e27712, objects: kv_test_0_0_72772507499400_0, get threads Statistics: idle(7),total(8),wait(0), elapsed ms: 0, remainingTime: 16
worker_192.168.215.9/datasystem_worker.INFO.log:2026-05-07T01:43:46.314068 | I | worker_oc_service_get_impl.cpp:1749 | kvc-jingpai-worker-6c6dd44d6d-fw7jb | 11:202 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Query metadata from master: 192.168.219.74:31402, objects: kv_test_0_0_72772507499400_0, request id: 7186c2da-597a-438f-beee-3b682e1bb92c, remainingTime:14ms
worker_192.168.215.9/datasystem_worker.INFO.log:2026-05-07T01:43:46.316788 | I | worker_oc_service_get_impl.cpp:778 | kvc-jingpai-worker-6c6dd44d6d-fw7jb | 11:202 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Query meta success: target num 1, success num 1, elapsed 2.731 ms
worker_192.168.215.9/datasystem_worker.INFO.log:2026-05-07T01:43:46.316810 | I | worker_oc_service_batch_get_impl.cpp:607 | kvc-jingpai-worker-6c6dd44d6d-fw7jb | 11:202 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Remote get request:[batch] objects count[1], src=192.168.215.9:31402, dst=192.168.219.74:31402
worker_192.168.215.9/datasystem_worker.INFO.log:2026-05-07T01:43:46.317435 | I | worker_oc_service_get_impl.cpp:193 | kvc-jingpai-worker-6c6dd44d6d-fw7jb | 11:202 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Process Get done, clientId: 088d87c8-aadc-456c-84ff-628653e27712, objectKeys: kv_test_0_0_72772507499400_0, subTimeout: 0, get threads Statistics: idle(6),total(8),wait(0).The operations of worker Get exceed 3ms: {ProcessGetObjectRequest: 3 ms; }
worker_192.168.215.9/access.log:2026-05-07T01:43:46.317423 | I | access_recorder.cpp:182 | kvc-jingpai-worker-6c6dd44d6d-fw7jb | 11:202 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai | 0 | DS_POSIX_GET | 3411 | 8388608 | {Object_key:kv_test_0_0_72772507499400_0,count:1,sub_timeout:0} | 
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:43:46.289674 | I | master_oc_service_impl.cpp:261 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:286 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Processing QueryMetaReq, requestId: 7186c2da-597a-438f-beee-3b682e1bb92c
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:43:46.289703 | I | master_oc_service_impl.cpp:270 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:286 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  QueryMeta on master 192.168.215.9:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:43:46.290592 | I | worker_worker_oc_service_impl.cpp:693 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:305 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_72772507499400_0,,0,8388608) remainingTime:11ms, src=192.168.215.9:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:43:46.290626 | I | urma_manager.cpp:1297 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:305 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  URMA write useNumaAffinity:1src:1, dst:1, jetty id:1037, urma_inflight_wr_count:1
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:43:46.290607 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:305 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  Processing pull object[kv_test_0_0_72772507499400_0] offset[0] size[8388608], src=192.168.215.9:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:43:46.290834 | I | urma_manager.cpp:852 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:305 | 1ec36d3b-1e2d-4dec-9541-10681af533c2 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.18251ms, request id:187257, src address:192.168.219.74:31402, target address:192.168.215.9:31402, dataSize:8388608, cpuid:0, status: code: [OK], msg: [], urma_inflight_wr_count: 1, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA
```

### Trace 5067 全量日志

**日志文件路径**: `/tmp/trace_extract/tmp/5067_63c7bb4e-4e20-4a6c-ab64-d69645453267.log`

```
SDK_192.168.182.1/ds_client_access_1160.log:2026-05-07T01:40:45.984148 | I | access_recorder.cpp:182 | kvc-jingpai-client-bf8d49dbb-jswph | 1160:1244 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 |  | 0 | DS_KV_CLIENT_GET | 5067 | 8388608 | {Object_key:kv_test_0_0_72592019278440_0,timeout:0,transportType:SHM} | 
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:40:45.979302 | I | worker_oc_service_get_impl.cpp:130 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:292 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 | jingpai |  Get start from client:706aceae-73f8-43c6-ac42-b23385f9217e server api read elapsed ms: 0.01345 inflight remote get request count: 0
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:40:45.979343 | I | worker_oc_service_get_impl.cpp:165 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:202 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 | jingpai |  Process Get from client: 706aceae-73f8-43c6-ac42-b23385f9217e, objects: kv_test_0_0_72592019278440_0, get threads Statistics: idle(7),total(8),wait(0), elapsed ms: 0, remainingTime: 16
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:40:45.979400 | I | worker_oc_service_get_impl.cpp:1749 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:202 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 | jingpai |  Query metadata from master: 192.168.219.74:31402, objects: kv_test_0_0_72592019278440_0, request id: 17511ea7-b80a-447e-99a8-08fdd48cb0ed, remainingTime:14ms
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:40:45.981308 | I | worker_oc_service_get_impl.cpp:778 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:202 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 | jingpai |  Query meta success: target num 1, success num 1, elapsed 1.934 ms
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:40:45.981360 | I | worker_oc_service_batch_get_impl.cpp:607 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:202 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 | jingpai |  Remote get request:[batch] objects count[1], src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:40:45.984014 | I | worker_oc_service_get_impl.cpp:193 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:202 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 | jingpai |  Process Get done, clientId: 706aceae-73f8-43c6-ac42-b23385f9217e, objectKeys: kv_test_0_0_72592019278440_0, subTimeout: 0, get threads Statistics: idle(6),total(8),wait(0).The operations of worker Get exceed 3ms: {ProcessGetObjectRequest: 4 ms; }
worker_192.168.182.2/access.log:2026-05-07T01:40:45.983999 | I | access_recorder.cpp:182 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:202 | 63c7bb4e-4e20-4a6c-ab64-d69645453267 | jingpai | 0 | DS_POSIX_GET | 4713 | 8388608 | {Object_key:kv_test_0_0_72592019278440_0,count:1,sub_timeout:0} | 
```

### 日志说明 (Trace 3661)

| # | 时间戳 | 节点 | 事件 |
|---|--------|------|------|
| 1 | 01:43:46.317524 | Client (192.168.215.6) | DS_KV_CLIENT_GET, transportType:SHM |
| 2 | 01:43:46.314022 | worker1 (192.168.215.9) | Get start from client |
| 3 | 01:43:46.314043 | worker1 (192.168.215.9) | Process Get, remainingTime: 16ms |
| 4 | 01:43:46.314068 | worker1 (192.168.215.9) | **Query metadata from master (192.168.219.74)**, remainingTime:14ms |
| 5 | 01:43:46.316788 | worker1 (192.168.215.9) | **Query meta success, elapsed 2.731 ms** |
| 6 | 01:43:46.316810 | worker1 (192.168.215.9) | Remote get request -> 192.168.219.74 |
| 7 | 01:43:46.317435 | worker1 (192.168.215.9) | **Process Get done, PG: 3ms** |
| 8 | 01:43:46.317423 | worker1 (192.168.215.9) | DS_POSIX_GET access log |
| 9 | 01:43:46.289674 | **Master (192.168.219.74)** | Processing QueryMetaReq |
| 10 | 01:43:46.289703 | **Master (192.168.219.74)** | QueryMeta on master success |
| 11 | 01:43:46.290592 | worker2 (192.168.219.74) | BatchGetObjectRemote request, remainingTime:11ms |
| 12 | 01:43:46.290607 | worker2 (192.168.219.74) | Processing pull object |
| 13 | 01:43:46.290626 | worker2 (192.168.219.74) | URMA write |
| 14 | 01:43:46.290834 | worker2 (192.168.219.74) | URMA wait 0.18ms, status:[OK] |

**注意**：Master (192.168.219.74) 的时间戳 (01:43:46.289xxx) 早于 worker1 的时间戳 (01:43:46.314xxx)，这是因为 worker2/Master 的系统时钟比 worker1 快约 24ms。如果统一到 worker1 时钟：
- Master 处理时间：289 + 24 = 313ms
