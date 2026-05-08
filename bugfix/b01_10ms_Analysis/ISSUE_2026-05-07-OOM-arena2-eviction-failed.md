# Issue: Shared Memory OOM - Eviction 大量失败导致 Arena 满

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 错误 (Error) |
| **影响组件** | Shared Memory / Object Cache / Eviction |
| **影响节点** | 192.168.219.108 |
| **严重程度** | Critical |
| **Trace ID** | 10143-0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 (示例) |

---

## 一、现象描述

**错误信息**: `Shared memory no space in arena: 2`

**关键现象**:
1. 28 个 trace 全部发生在节点 **192.168.219.108**
2. 所有 OOM 都指向 **arena 2**
3. **EvictionList 有 1221-1225 项待驱逐，但几乎全部失败 (1221/1222 失败)**
4. 驱逐失败原因: 对象在 ObjectTable 中不存在 (`Key not found`)
5. 导致共享内存 arena 2 耗尽，新请求无法分配内存

**推测**: 驱逐列表中的对象与 ObjectTable 状态不一致，导致驱逐机制失效。

---

## 二、日志证据

### 2.1 核心错误日志

```
worker_192.168.219.108: EvictionList size before evict: 1221
worker_192.168.219.108: [ObjectKey kv_test_22_2_87827079502240_0] Error while allocating memory. Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]
worker_192.168.219.108: [ObjectKey kv_test_17_0_87780391557530_0] Object not in ObjectTable, code: [Key not found]
worker_192.168.219.108: evict action unknown, total cost 0.01204 ms, obj size: 0status:GetAndLockEntry failed Thread ID 281391841934560 Key not found. Object does not exist.
worker_192.168.219.108: EvictionList size after evict:1222, failed size:1221
```

### 2.2 全量日志 (trace 10143-0953a763)

```
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733677:2026-05-07T05:54:10.468423 | I | master_oc_service_impl.cpp:261 | 192.168.210.230 | 11:272 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Processing QueryMetaReq, requestId: 2bbfe745-1c49-4af6-ac33-56b1286dd599
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733678:2026-05-07T05:54:10.468432 | I | master_oc_service_impl.cpp:270 | 192.168.210.230 | 11:272 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  QueryMeta on master 192.168.219.108:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733725:2026-05-07T05:54:10.470912 | I | master_oc_service_impl.cpp:295 | 192.168.210.230 | 11:270 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Master received RemoveMeta req: address: "192.168.219.108:31402" ids: "kv_test_22_2_87827079502240_0" cause: EVICTION timeout: 6 version: 1778104450218058 signature: "***" access_key: "***"
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733726:2026-05-07T05:54:10.470919 | I | oc_metadata_manager.cpp:1696 | 192.168.210.230 | 11:270 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Objects kv_test_22_2_87827079502240_0] Start to remove meta location 192.168.219.108:31402
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733727:2026-05-07T05:54:10.470925 | I | oc_metadata_manager.cpp:1484 | 192.168.210.230 | 11:270 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  RemoveMeta finished, receive id size: 1, success size: 1, need wait size: 0, need data size: 0, failed size: 0, outdated size: 0
worker_192.168.210.230/datasystem_worker.INFO.20260507055451_454.log.gz:733728:2026-05-07T05:54:10.470929 | I | master_oc_service_impl.cpp:305 | 192.168.210.230 | 11:270 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  The operations of master RemoveMeta exceed 3ms: {}
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204034:2026-05-07T05:54:10.213700 | I | worker_oc_service_get_impl.cpp:130 | 192.168.219.108 | 11:290 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Get] Receive, clientId: af46f30a-d127-47f0-a17e-44bd61c9458f, serverApiReadCost: 0.004ms, inflightRemoteGet: 1
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204039:2026-05-07T05:54:10.213739 | I | worker_oc_service_get_impl.cpp:165 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Get] Receive, clientId: af46f30a-d127-47f0-a17e-44bd61c9458f, objects: kv_test_22_2_87827079502240_0, threadPool: idle(16),total(22),wait(1), elapsed: 0.000ms, remainingTime: 14.000ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204041:2026-05-07T05:54:10.213764 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Query metadata from master: 192.168.210.230:31402, objects: kv_test_22_2_87827079502240_0, request id: 2bbfe745-1c49-4af6-ac33-56b1286dd599, remainingTime:12ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204081:2026-05-07T05:54:10.217938 | I | worker_oc_service_get_impl.cpp:780 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Get] Master query done, targets: 1, hits: 1, cost: 4.183ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204093:2026-05-07T05:54:10.217976 | I | worker_oc_eviction_manager.cpp:421 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Eviction start.
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204096:2026-05-07T05:54:10.217995 | I | worker_oc_eviction_manager.cpp:292 | 192.168.219.108 | 11:239 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  EvictionList size before evict: 1221
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204099:2026-05-07T05:54:10.218039 | E | obj_cache_shm_unit.cpp:256 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [ObjectKey kv_test_22_2_87827079502240_0] Error while allocating memory. Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2, traceId: 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7]
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204100:2026-05-07T05:54:10.218042 | I | worker_oc_service_batch_get_impl.cpp:389 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [ObjectKey kv_test_22_2_87827079502240_0] Out of memory, get remote abort.
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204101:2026-05-07T05:54:10.218050 | E | worker_oc_service_batch_get_impl.cpp:204 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  BatchGetObjectFromRemoteOnLock failed. Detail: code: [Out of memory], msg: [Thread ID 281279192038624 Out of memory. Request not ready for the remote get request to addr: 192.168.89.38:31402, due to Shared memory no space in arena: 2, traceId: 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204110:2026-05-07T05:54:10.218053 | I | worker_oc_service_get_impl.cpp:545 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  delete unacked object meta, size: 1
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204246:2026-05-07T05:54:10.220540 | I | worker_request_manager.cpp:388 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  Can't find object kv_test_22_2_87827079502240_0, clientId af46f30a-d127-47f0-a17e-44bd61c9458f
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204247:2026-05-07T05:54:10.220526 | I | worker_oc_service_get_impl.cpp:516 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  TryGetObjectFromRemote failed, detail: code: [Out of memory], msg: [Thread ID 281279192038624 Out of memory. Request not ready for the remote get request to addr: 192.168.89.38:31402, due to Shared memory no space in arena: 2, traceId: 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204262:2026-05-07T05:54:10.220586 | I | worker_oc_service_get_impl.cpp:194 | 192.168.219.108 | 11:422 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [Get] Done, clientId: af46f30a-d127-47f0-a17e-44bd61c9458f, objects: 1, transferPath: UB, totalCost: exceed 3ms: {Worker to master rpc QueryMeta: 4 ms; ProcessGetObjectRequest: 6 ms; }
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204335:2026-05-07T05:54:10.220943 | W | worker_oc_eviction_manager.cpp:741 | 192.168.219.108 | 11:239 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [ObjectKey kv_test_17_0_87780391557530_0] Object not in ObjectTable, code: [Key not found], msg: [Thread ID 281391841934560 Key not found. Object does not exist.
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204338:traceId      : 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7].
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204340:2026-05-07T05:54:10.220952 | I | worker_oc_eviction_manager.h:197 | 192.168.219.108 | 11:239 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  [TaskId kv_test_17_0_87780391557530_0] evict action unknown, total cost 0.01204 ms, obj size: 0status:GetAndLockEntry failed Thread ID 281391841934560 Key not found. Object does not exist.
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204343:traceId      : 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7].
worker_192.168.219.108/datasystem_worker.INFO.20260507055426_949.log.gz:1204413:2026-05-07T05:54:10.221309 | I | worker_oc_eviction_manager.cpp:344 | 192.168.219.108 | 11:239 | 0953a763-cf5a-4fcc-b0ba-e9cf26bcdbf7 | jingpai |  EvictionList size after evict:1222, failed size:1221
```

---

## 三、根因分析

### 3.1 问题节点统计

| 节点 | OOM 次数 |
|------|----------|
| 192.168.219.108 | 28 (100%) |
| 192.168.42.102 | 5 |
| 192.168.35.39 | 5 |
| 192.168.168.230 | 3 |
| 192.168.210.230 | 2 |

### 3.2 Arena 统计

所有 28 个 OOM trace 都指向 **arena 2**。

### 3.3 驱逐失败分析

```
EvictionList size before evict: 1221
EvictionList size after evict: 1222, failed size: 1221
```

- 驱逐前有 1221 项
- 驱逐后只剩 1 项减少 (1222 - 1221 = 1)
- **失败 1221 项，成功仅 1 项**

### 3.4 失败原因

```
[ObjectKey kv_test_17_0_87780391557530_0] Object not in ObjectTable, code: [Key not found]
evict action unknown, total cost 0.01204 ms, obj size: 0status:GetAndLockEntry failed Thread ID 281391841934560 Key not found. Object does not exist.
```

**对象在 ObjectTable 中不存在**，导致无法驱逐。

---

## 四、疑似 Bug 分析

### Bug 1: ObjectTable 与驱逐列表状态不一致

驱逐列表中的对象在 ObjectTable 中不存在。可能原因：

1. **竞态条件**: 对象在加入驱逐列表后、被驱逐前被删除
2. **元数据不一致**: Master 和 Worker 的 metadata 同步问题
3. **驱逐列表清理遗漏**: 已删除的对象没有被从驱逐列表中移除

### Bug 2: Eviction 失败后没有有效回退机制

驱逐失败后：
1. 大部分驱逐尝试都失败了
2. 失败后没有有效的回退机制
3. 内存持续占用直到完全耗尽

---

## 五、影响 Trace 列表

| Trace ID | EvictionList Size | Failed Size |
|----------|------------------|-------------|
| 10143-0953a763 | 1221 | 1221 |
| 10155-6f7f264d | 1219 | - |
| 10285-cd82260e | - | - |
| 10348-fbd344bc | - | - |
| 10501-8ca9e472 | - | - |
| 11262-eca84068 | 1225 | - |
| ... | ... | ... |

(共 28 个 OOM trace)

---

## 六、建议

1. **检查 EvictionManager 代码**
   - 为什么对象不在 ObjectTable 中却被加入驱逐列表？
   - 驱逐失败后的错误处理是否正确？

2. **增加监控**
   - 驱逐失败率超过阈值应该告警
   - ObjectTable 与驱逐列表的一致性检查

3. **增加内存容量或优化配置**
   - 192.168.219.108 可能需要更多共享内存
   - 或者调整 arena 大小配置
