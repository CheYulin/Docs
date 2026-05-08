# Issue: b01 全量大于 10ms Trace 分析

## 测试场景

- **采集条件**: 全量大于 10ms 的 Trace
- **Trace 数**: 124 个

---

## 一、异常分类汇总

| 异常类型 | Trace 数 | 说明 |
|----------|---------|------|
| **Out of memory** | 28 | 共享内存耗尽 |
| **高 QueryMeta** (>5ms) | 10 | Master 处理延迟 |
| **高 ProcessGetObjectRequest** (>10ms) | 8 | RPC 处理延迟 |
| **高 URMA Wait** (>1ms) | 1 | URMA 性能异常 |
| **Failed** | 36 | RPC 调用失败 |
| **正常** | 41 | 无明显异常 |

---

## 二、关键 Trace 详细分析

### 2.1 高 URMA Wait Trace: 10084-dd8c385c

**URMA Wait: 2.32ms (异常 > 1ms)**

#### 时间线分析

| 时间 | 节点 | 事件 |
|------|------|------|
| 05:53:56.634311 | Worker2 (192.168.219.108) | 收到 RemotePull 请求 |
| 05:53:56.634327 | Worker2 | URMA write 开始 |
| 05:53:56.636673 | Worker2 | URMA wait 完成, **cost 2.32ms** |
| 05:53:56.802617 | Worker1 (192.168.233.102) | 收到 Get 请求 |
| 05:53:56.802951 | Worker1 | QueryMeta 完成, cost 0.309ms |
| 05:53:56.812404 | Worker1 | Get Done, PG=9ms |

#### 异常点

- **URMA wait 2.32ms**: 正常应该 < 1ms
- **inflight_wr_count=6**: URMA 队列有积压

---

### 2.2 高 ProcessGetObjectRequest Trace: 18736-c0689a13

**PG=14ms, QM=5ms**

#### 时间线分析

| 时间 | 节点 | 事件 |
|------|------|------|
| 06:01:24.540238 | Worker1 (192.168.219.108) | 收到 Get 请求 |
| 06:01:24.540310 | Worker1 | QueryMeta 开始, remainingTime:14ms |
| 06:01:24.545626 | Worker1 | QueryMeta 完成, cost **5.332ms** |
| 06:01:24.545657 | Worker1 | RemotePull 开始 |
| 06:01:24.798709 | Worker2 (192.168.182.39) | 收到 RemotePull |
| 06:01:24.799087 | Worker2 | URMA write 开始 |
| 06:01:24.799431 | Worker2 | URMA wait 完成, cost **0.34ms** |
| 06:01:24.554689 | Worker1 | Get Done, PG=**14ms** |

#### 各阶段耗时

| 阶段 | 耗时 | 说明 |
|------|------|------|
| **client -> worker1** | - | 未采集 |
| **worker1 -> meta** | 5.332ms | QueryMeta 耗时 |
| **worker1 -> worker2** | 约 253ms | RemotePull 请求发送 |
| **worker2 urma write** | 0.34ms | 正常 |
| **worker2 urma wait** | - | 无等待 |

#### 异常点

- **worker1 -> worker2 约 253ms**: 从 QueryMeta 完成到 Worker2 收到请求间隔过长
- **PG=14ms**: 整体处理时间较长

---

### 2.3 Out of memory Trace: 10143-0953a763

**错误: Out of memory**

#### 全量日志

```
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733677:2026-05-07T05:54:10.468423 | I | master_oc_service_impl.cpp:261 | 192.168.210.230 | 11:272 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Processing QueryMetaReq, requestId: 2bbfe745-1c49-4af6-ac33-56b1286dd599
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733678:2026-05-07T05:54:10.468432 | I | master_oc_service_impl.cpp:270 | 192.168.210.230 | 11:272 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  QueryMeta on master 192.168.219.108:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204039:2026-05-07T05:54:10.213739 | I | worker_oc_service_get_impl.cpp:165 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Get] Receive, clientId: af46f30a-d127-47f0-a17e-44bd61c9458f, objects: kv_test_22_2_87827079502240_0, threadPool: idle(16),total(22),wait(1), elapsed: 0.000ms, remainingTime: 14.000ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204041:2026-05-07T05:54:10.213764 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Query metadata from master: 192.168.210.230:31402, objects: kv_test_22_2_87827079502240_0, request id: 2bbfe745-1c49-4af6-ac33-56b1286dd599, remainingTime:12ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204081:2026-05-07T05:54:10.217938 | I | worker_oc_service_get_impl.cpp:780 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Get] Master query done, targets: 1, hits: 1, cost: 4.183ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204093:2026-05-07T05:54:10.217976 | I | worker_oc_eviction_manager.cpp:421 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Eviction start.
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204096:2026-05-07T05:54:10.217995 | I | worker_oc_eviction_manager.cpp:292 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  EvictionList size before evict: 1221
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204099:2026-05-07T05:54:10.218039 | E | obj_cache_shm_unit.cpp:256 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [ObjectKey kv_test_22_2_87827079502240_0] Error while allocating memory. Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2, traceId: 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7]
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204100:2026-05-07T05:54:10.218042 | I | worker_oc_service_batch_get_impl.cpp:389 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [ObjectKey kv_test_22_2_87827079502240_0] Out of memory, get remote abort.
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204101:2026-05-07T05:54:10.218050 | E | worker_oc_service_batch_get_impl.cpp:204 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  BatchGetObjectFromRemoteOnLock failed. Detail: code: [Out of memory], msg: [Thread ID 281279192038624 Out of memory. Request not ready for the remote get request to addr: 192.168.89.38:31402, due to Shared memory no space in arena: 2, traceId: 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7]
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204246:2026-05-07T05:54:10.220540 | I | worker_request_manager.cpp:388 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Can't find object kv_test_22_2_87827079502240_0, clientId af46f30a-d127-47f0-a17e-44bd61c9458f
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204247:2026-05-07T05:54:10.220526 | I | worker_oc_service_get_impl.cpp:516 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  TryGetObjectFromRemote failed, detail: code: [Out of memory], msg: [Thread ID 281279192038624 Out of memory. Request not ready for the remote get request to addr: 192.168.89.38:31402, due to Shared memory no space in arena: 2, traceId: 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7]
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204262:2026-05-07T05:54:10.220586 | I | worker_oc_service_get_impl.cpp:194 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Get] Done, clientId: af46f30a-d127-47f0-a17e-44bd61c9458f, objects: 1, transferPath: UB, totalCost: exceed 3ms: {Worker to master rpc QueryMeta: 4 ms; ProcessGetObjectRequest: 6 ms; }
```

#### 根因分析

- **错误**: `Shared memory no space in arena: 2`
- **影响节点**: 192.168.219.108
- **EvictionList size**: 1221 (驱逐列表很大，说明缓存已满)

---

## 三、高 QueryMeta 集群分析

### 3.1 11ms QueryMeta 集群 (12 个 trace)

这些 trace 的 QM 都是 11ms，呈集群分布：

| Trace ID | QM | PG | 时间 |
|----------|-----|-----|------|
| 11419-17202969 | 11ms | 11ms | 05:52:xx |
| 11423-3a59688f | 11ms | 11ms | 05:52:xx |
| 11430-fcd978d5 | 11ms | 11ms | 05:52:xx |
| 11432-1e5d2d9f | 11ms | 11ms | 05:52:xx |
| 11450-ece01367 | 11ms | 11ms | 05:52:xx |
| 11455-fdbc3d5c | 11ms | 11ms | 05:52:xx |
| 11473-f2c0258f | 11ms | 11ms | 05:52:xx |
| 11529-b6a41c1f | 11ms | 11ms | 05:52:xx |
| 11532-b3c27034 | 11ms | 11ms | 05:52:xx |
| 11551-62b9fed3 | 11ms | 11ms | 05:52:xx |
| 11563-a707c756 | 11ms | 11ms | 05:52:xx |
| 12013-0624252e | 11ms | 11ms | 05:53:xx |

### 3.2 示例: 11450-ece01367 详细分析

#### 全量日志

```
worker_192.168.168.230/datasystem_worker.INFO.20260507055216_160.log.gz:29499:2026-05-07T05:50:53.720302 | I | master_oc_service_impl.cpp:261 | 192.168.168.230 | 11:287 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  Processing QueryMetaReq, requestId: 6bef54ea-7634-4f98-a2e1-6324b0fa145b
worker_192.168.168.230/datasystem_worker.INFO.20260507055216_160.log.gz:29500:2026-05-07T05:50:53.720314 | I | master_oc_service_impl.cpp:270 | 192.168.168.230 | 11:287 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  QueryMeta on master 192.168.210.230:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19397:2026-05-07T05:50:53.794124 | I | worker_oc_service_get_impl.cpp:130 | 192.168.210.230 | 11:278 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  [Get] Receive, clientId: 37d33300-8dcf-4244-b30b-92020daa1bd8, serverApiReadCost: 0.006ms, inflightRemoteGet: 0
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19398:2026-05-07T05:50:53.794143 | I | worker_oc_service_get_impl.cpp:165 | 192.168.210.230 | 11:190 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  [Get] Receive, clientId: 37d33300-8dcf-4244-b30b-92020daa1bd8, objects: kv_test_6_12_87631942853660_0, threadPool: idle(6),total(8),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19399:2026-05-07T05:50:53.794162 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.210.230 | 11:190 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  Query metadata from master: 192.168.168.230:31402, objects: kv_test_6_12_87631942853660_0, request id: 6bef54ea-7634-4f98-a2e1-6324b0fa145b, remainingTime:14ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19461:2026-05-07T05:50:53.805264 | E | rpc_util.h:115 | 192.168.210.230 | 11:190 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  [RPC Retry]: code: [RPC unavailable], msg: [[RPC_RECV_TIMEOUT] Rpc service for client fb22983d-4f5a-4929:6:281342372282704:0 has not responded within the allowed time. Detail: code: [Try again], msg: [Thread ID 281428886027488 Try again. The queue is empty within allowed time: 11 ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19468:2026-05-07T05:50:53.805271 | E | worker_oc_service_get_impl.cpp:1535 | 192.168.210.230 | 11:190 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  Query metadata from master[192.168.168.230:31402]: code: [RPC unavailable], msg: [[RPC_RECV_TIMEOUT] Rpc service for client fb22983d-4f5a-4929:6:281342372282704:0 has not responded within the allowed time. Detail: code: [Try again], msg: [Thread ID 281428886027488 Try again. The queue is empty within allowed time: 11 ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19473:2026-05-07T05:50:53.805305 | I | worker_request_manager.cpp:388 | 192.168.210.230 | 11:190 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  Can't find object kv_test_6_12_87631942853660_0, clientId 37d33300-8dcf-4244-b30b-92020daa1bd8
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19474:2026-05-07T05:50:53.805332 | I | worker_oc_service_get_impl.cpp:194 | 192.168.210.230 | 11:190 | ece01367-a0ce-4742-9f5c-4c9e0f3d0c0f | jingpai |  [Get] Done, clientId: 37d33300-8dcf-4244-b30b-92020daa1bd8, objects: 1, transferPath: UB, totalCost: exceed 3ms: {Worker to master rpc QueryMeta: 11 ms; ProcessGetObjectRequest: 11 ms; }
```

#### 时间线分析

| 时间 | 节点 | 事件 | 耗时 |
|------|------|------|------|
| 05:50:53.720302 | Master (192.168.168.230) | Processing QueryMetaReq | - |
| 05:50:53.794124 | Worker1 (192.168.210.230) | 收到 Get 请求 | - |
| 05:50:53.794162 | Worker1 | QueryMeta 开始 | - |
| 05:50:53.805264 | Worker1 | **RPC Retry**, timeout 11ms | - |
| 05:50:53.805305 | Worker1 | Can't find object | QM=11ms |

#### 根因分析

- **RPC Retry**: QueryMeta RPC 超时 11ms 后重试
- **queue is empty within allowed time**: Master 处理队列积压
- **根因**: Master (192.168.168.230) 处理延迟

---

## 四、高 ProcessGetObjectRequest 分析

### 4.1 全量 PG > 10ms Trace

| Trace ID | PG | QM | URMA | 说明 |
|----------|-----|-----|------|------|
| 20321-2bbff09e | 17ms | - | - | timeout |
| 18736-c0689a13 | 14ms | 5ms | 0.34ms | |
| 19535-78141748 | 14ms | 5ms | 0.25ms | |
| 19598-024ebb73 | 14ms | - | - | |
| 14446-6f3a059f | 12ms | - | - | |
| 11959-6c93605c | 11ms | - | - | |
| 12012-c642fb0d | 11ms | 5ms | 0.26ms | |
| 20370-b7303612 | 11ms | 3ms | 0.18ms | |

### 4.2 示例: 20321-2bbff09e (PG=17ms 最高)

```
worker_192.168.219.108/datasystem_worker.INFO.log:93928:2026-05-07T06:01:24.540271 | I | worker_oc_service_get_impl.cpp:130 | 192.168.219.108 | 11:290 | 2bbff09e-4210-4505-82b9-67202e816225 | jingpai |  [Get] Receive, clientId: fb7e3d58-4ade-4059-af52-fe5fad79ef9a, serverApiReadCost: 0.005ms, inflightRemoteGet: 3
worker_192.168.219.108/datasystem_worker.INFO.log:93931:2026-05-07T06:01:24.540373 | I | worker_oc_service_get_impl.cpp:165 | 192.168.219.108 | 11:447 | 2bbff09e-4210-4505-82b9-67202e816225 | jingpai |  [Get] Receive, clientId: fb7e3d58-4ade-4059-af52-fe5fad79ef9a, objects: kv_test_26_6_88281458205490_0, threadPool: idle(23),total(34),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms
worker_192.168.219.108/datasystem_worker.INFO.log:94273:2026-05-07T06:01:24.557583 | E | worker_request_manager.cpp:329 | 192.168.219.108 | 11:447 | 2bbff09e-4210-4505-82b9-67202e816225 | jingpai |  ReturnFromGetRequest timeout when get object: kv_test_26_6_88281458205490_0
worker_192.168.219.108/datasystem_worker.INFO.log:94300:2026-05-07T06:01:24.557637 | I | worker_oc_service_get_impl.cpp:194 | 192.168.219.108 | 11:447 | 2bbff09e-4210-4505-82b9-67202e816225 | jingpai |  [Get] Done, clientId: fb7e3d58-4ade-4059-af52-fe5fad79ef9a, objects: 1, transferPath: UB, totalCost: exceed 3ms: {ProcessGetObjectRequest: 17 ms; }
```

#### 根因分析

- **ReturnFromGetRequest timeout**: RemoteGet 超时
- **inflightRemoteGet: 3**: 当时有 3 个正在进行的远程获取请求
- **PG=17ms**: 从 540.271 到 557.637，约 17ms

---

## 五、根因总结

### 5.1 Out of memory (28 个 trace)

| 影响节点 | 出现次数 |
|----------|----------|
| 192.168.219.108 | 多次 |
| 192.168.210.230 | 多次 |

**根因**: 共享内存 arena 耗尽，无法分配新内存。

### 5.2 高 QueryMeta (10 个 trace)

**根因**: Master 处理队列积压，导致 RPC 超时重试。

### 5.3 高 ProcessGetObjectRequest (8 个 trace)

**根因**: RemoteGet 超时，可能与网络延迟或 Worker2 处理延迟有关。

### 5.4 高 URMA Wait (1 个 trace)

**根因**: URMA 队列积压 (inflight_wr_count=6)，导致等待时间增加。

---

## 六、建议

1. **调查内存问题**
   - 为什么共享内存耗尽
   - 是否需要增加内存或调整内存分配策略

2. **调查问题节点**
   - 192.168.219.108 是主要问题节点
   - 可能需要增加该节点的资源

3. **增加监控告警**
   - Out of memory 错误不应该发生
   - QueryMeta > 5ms 应该告警
   - PG > 10ms 应该告警
