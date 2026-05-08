# Issue: RPC Client 请求准备延迟分析 (662us - 3668us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 + 业务错误 |
| **影响组件** | RPC Client -> RPC Server |
| **影响节点** | Worker1 (RPC Client) / Worker2 (RPC Server) |
| **严重程度** | **High** |
| **Trace ID** | metrics_client_req_framework_us_min_662_max_3668 |

---

## 一、概念澄清：RPC Client vs 外部 Client

### 重要区分

| 概念 | 含义 |
|------|------|
| **外部 Client** | 终端用户，发起 Get 请求 |
| **RPC Client** | Worker1，收到外部 Client 请求后，向 Worker2 发起远程调用 |
| **RPC Server** | Worker2，处理 Worker1 的远程调用请求 |

### 系统流程

```
外部 Client                  Worker1                    Worker2
   │                        (RPC Client)              (RPC Server)
   │                             │                          │
   │------ Get Request -------->│                          │
   │                             │                          │
   │                             │--- Remote Get --------->│
   │                             │    (RPC 调用)            │
   │                             │                          │
   │                             │<-- Data (URMA) --------│
   │                             │                          │
   │<------- Get Response -------│                          │
   │                             │                          │
```

### ZMQ RPC 指标定义

根据 `zmq_constants.h:172-188`：

```cpp
// client_req_framework = RPC Client 发送请求到 RPC Server 收到请求的时间
uint64_t clientReqFrameworkNs = (clientSendTs > clientStartTs) ? (clientSendTs - clientStartTs) : 0U;
```

**client_req_framework** 是 **Worker1 (RPC Client)** 准备请求并发送，到 **Worker2 (RPC Server)** 收到请求的时间。

---

## 二、错误日志分析

### 错误 Trace 1: de7e919b

```
14:40:06.742349 | E | obj_cache_shm_unit.cpp:256 | 192.168.219.66 | Error while allocating memory.
   Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]

14:40:06.742353 | I | worker_oc_service_batch_get_impl.cpp:389 | Out of memory, get remote abort.

14:40:06.742362 | E | worker_oc_service_batch_get_impl.cpp:204 | BatchGetObjectFromRemoteOnLock failed.
   Detail: code: [Out of memory], msg: [Thread ID ... Out of memory.
   Request not ready for the remote get request to addr: 192.168.210.253:31402,
   due to Shared memory no space in arena: 2]
```

### 错误 Trace 2: 2fd8e0c7

```
14:40:06.742282 | E | obj_cache_shm_unit.cpp:256 | 192.168.219.66 | Error while allocating memory.
   Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]

14:40:06.742297 | E | worker_oc_service_batch_get_impl.cpp:244 | Failed to get object data from remote.
   lastRc: code: [Out of memory], msg: [Thread ID ... Out of memory.
   Request not ready for the remote get request to addr: 192.168.182.24:31402]
```

### 错误 Trace 3: cccd1dea

```
14:36:06.663937 | E | obj_cache_shm_unit.cpp:256 | 192.168.219.66 | Error while allocating memory.
   Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]

14:36:06.663949 | E | worker_oc_service_batch_get_impl.cpp:204 | BatchGetObjectFromRemoteOnLock failed.
   Detail: code: [Out of memory], msg: [Thread ID ... Out of memory.
   Request not ready for the remote get request to addr: 192.168.210.253:31402]
```

---

## 三、Framework 分解

### 正常 Trace (1402f5f1)

```
framework_us=3660
  client_req_framework_us=2510       // ⚠️ 较高
  remote_processing_us=1457
  client_rsp_framework_us=17
  server_req_queue_us=20
  server_exec_us=325
  server_rsp_queue_us=19
  network_residual_us=1092
```

### 异常 Trace (de7e919b) - Out of Memory

```
framework_us=3424
  client_req_framework_us=3166       // ⚠️ 异常高
  remote_processing_us=271          // 处理失败，较低
  client_rsp_framework_us=19
  server_req_queue_us=22
  server_exec_us=32                 // 执行时间短（失败）
  server_rsp_queue_us=14
  network_residual_us=202           // 网络传输短（未真正传输）
```

### 异常 Trace (2fd8e0c7) - Out of Memory

```
framework_us=4748
  client_req_framework_us=3273       // ⚠️ 异常高 (max: 3668us)
  remote_processing_us=1496
  client_rsp_framework_us=19
  server_req_queue_us=17
  server_exec_us=41                 // 执行时间短（失败）
  server_rsp_queue_us=20
  network_residual_us=1417
```

---

## 四、根因分析

### 4.1 Out of Memory 错误链

```
1. Worker1 收到外部 Client 的 Get 请求
2. Worker1 查询 Master 元数据，找到对象在 Worker2 上
3. Worker1 准备向 Worker2 发起远程 Get
4. Worker1 尝试分配共享内存 (Shared Memory Arena)
   ❌ 失败: Shared memory no space in arena: 2
5. 触发 Eviction Manager 清理内存
6. Eviction 失败 (EvictionList size after evict:1223, failed size:1222)
7. 最终失败: BatchGetObjectFromRemoteOnLock failed
```

### 4.2 代码确认

**文件**: `obj_cache_shm_unit.cpp:256`

```cpp
// 共享内存分配失败
if (shmUnit == nullptr || shmUnit->size == 0) {
    LOG(ERROR) << "Error while allocating memory. "
               << "Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]";
    return Status(K_NO_MEMORY, "Shared memory no space in arena: 2");
}
```

**文件**: `worker_oc_eviction_manager.cpp:421-431`

```cpp
LOG(INFO) << "Eviction start.";
LOG(INFO) << "Evict is going on...";
// 尝试清理内存...
```

### 4.3 关键发现

1. **节点 192.168.219.66 内存不足**
   - 所有 3 个错误都发生在同一个节点
   - `inflightRemoteGet: 1` 表示有远程请求在飞

2. **Eviction 失败**
   ```
   EvictionList size before evict: 1222
   EvictionList size after evict: 1223, failed size: 1222
   ```
   - 1222 个对象尝试 eviction，全部失败
   - 说明节点内存压力严重

3. **client_req_framework 高的原因**
   - Out of memory 导致重试和 eviction 尝试
   - 分配内存的时间被计入 client_req_framework

---

## 五、结论

| 问题 | 答案 |
|------|------|
| client_req_framework 是什么？ | Worker1 (RPC Client) 发送请求到 Worker2 (RPC Server) 收到的时间 |
| 延迟多少？ | **662us - 3668us** |
| 主要错误？ | **Out of memory** - Shared memory arena 满 |
| 影响节点？ | **192.168.219.66** |
| 根因？ | 节点内存不足，Eviction 失败 |

**根因**: Worker1 (192.168.219.66) 共享内存不足，导致对象分配失败。虽然后续尝试 eviction 清理内存，但 1222 个对象全部 evict 失败，最终导致 Get 请求失败。

---

## 六、建议

1. **扩容 Worker 内存** (P0)
   - 增加 Shared memory arena 大小
   - 监控 `no space in arena` 错误频率

2. **优化 Eviction 策略** (P0)
   - 当前 eviction 全部失败
   - 检查 LRU/LFU 策略是否合理

3. **负载均衡** (P1)
   - 192.168.219.66 负载过高
   - 分散请求到其他节点

---

## 附录 A：全量日志

### Trace de7e919b - Out of Memory

```
// Worker1 (192.168.219.66) 侧

14:40:06.741696 | I | worker_oc_service_get_impl.cpp:130 | [Get] Receive, clientId: f8106d40-21a1-48d5-9bd7-70f539ec34d1, serverApiReadCost: 0.007ms, inflightRemoteGet: 1

14:40:06.741721 | I | worker_oc_service_get_impl.cpp:165 | threadPool: idle(18),total(20),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms

14:40:06.741747 | I | worker_oc_service_get_impl.cpp:1752 | Query metadata from master: 192.168.35.22:31402

14:40:06.742300 | I | worker_oc_service_get_impl.cpp:780 | Master query done, targets: 1, hits: 1, cost: 0.559ms

14:40:06.742319 | I | worker_oc_eviction_manager.cpp:421 | Eviction start.

14:40:06.742329 | I | worker_oc_eviction_manager.cpp:431 | Evict is going on...

14:40:06.742349 | E | obj_cache_shm_unit.cpp:256 | [ObjectKey kv_test_5_4_119375649034470_0] Error while allocating memory. Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2, traceId: de7e919b-9586-400b-a39c-c2d9fca16017]

14:40:06.742353 | I | worker_oc_service_batch_get_impl.cpp:389 | [ObjectKey kv_test_5_4_119375649034470_0] Out of memory, get remote abort.

14:40:06.742362 | E | worker_oc_service_batch_get_impl.cpp:204 | BatchGetObjectFromRemoteOnLock failed. Detail: code: [Out of memory], msg: [Thread ID 281386198432992 Out of memory. Request not ready for the remote get request to addr: 192.168.210.253:31402, due to Shared memory no space in arena: 2, traceId: de7e919b-9586-400b-a39c-c2d9fca16017]

14:40:06.742365 | E | worker_oc_service_batch_get_impl.cpp:244 | Failed to get object data from remote. 0 objects pulled success: [], meta data num: 1 lastRc: code: [Out of memory], msg: [Thread ID 281386198432992 Out of memory. Request not ready for the remote get request to addr: 192.168.210.253:31402, due to Shared memory no space in arena: 2, traceId: de7e919b-9586-400b-a39c-c2d9fca16017]

14:40:06.745872 | I | zmq_constants.h:204 | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=de7e919b-9586-400b-a39c-c2d9fca16017 framework_us=3424 e2e_us=3457 client_req_framework_us=3166 remote_processing_us=271 client_rsp_framework_us=19 server_req_queue_us=22 server_exec_us=32 server_rsp_queue_us=14 network_residual_us=202

14:40:06.745903 | I | worker_oc_service_get_impl.cpp:516 | TryGetObjectFromRemote failed, detail: code: [Out of memory], msg: [Thread ID 281386198432992 Out of memory...]

14:40:06.745911 | I | worker_request_manager.cpp:388 | Can't find object kv_test_5_4_119375649034470_0

14:40:06.745962 | I | worker_oc_service_get_impl.cpp:194 | [Get] Done, clientId: f8106d40-21a1-48d5-9bd7-70f539ec34d1, objects: 1, transferPath: UB, totalCost: exceed 3ms: {Worker to master rpc RemoveMeta: 3 ms; ProcessGetObjectRequest: 4 ms; }
```

### Trace 2fd8e0c7 - Out of Memory

```
14:40:06.741720 | I | worker_oc_service_get_impl.cpp:130 | [Get] Receive, clientId: f8106d40-21a1-48d5-9bd7-70f539ec34d1, serverApiReadCost: 0.004ms, inflightRemoteGet: 1

14:40:06.741751 | I | worker_oc_service_get_impl.cpp:165 | threadPool: idle(17),total(20),wait(0)

14:40:06.741769 | I | worker_oc_service_get_impl.cpp:1752 | Query metadata from master: 192.168.45.216:31402

14:40:06.742262 | I | worker_oc_eviction_manager.cpp:421 | Eviction start.

14:40:06.742276 | I | worker_oc_eviction_manager.cpp:292 | EvictionList size before evict: 1222

14:40:06.742282 | E | obj_cache_shm_unit.cpp:256 | Error while allocating memory. Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]

14:40:06.742288 | I | worker_oc_service_batch_get_impl.cpp:389 | Out of memory, get remote abort.

14:40:06.742297 | E | worker_oc_service_batch_get_impl.cpp:204 | BatchGetObjectFromRemoteOnLock failed. Detail: code: [Out of memory], msg: [Thread ID 281293569195232 Out of memory. Request not ready for the remote get request to addr: 192.168.182.24:31402]

14:40:06.746856 | I | worker_oc_eviction_manager.cpp:344 | EvictionList size after evict:1223, failed size:1222

14:40:06.747146 | I | zmq_constants.h:204 | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=2fd8e0c7-671e-4a1b-b9fb-47db0f4808ed framework_us=4748 e2e_us=4789 client_req_framework_us=3273 remote_processing_us=1496 client_rsp_framework_us=19 server_req_queue_us=17 server_exec_us=41 server_rsp_queue_us=20 network_residual_us=1417
```

---

## 附录 B：相关代码

### B.1 共享内存分配

**文件**: `obj_cache_shm_unit.cpp:256`

```cpp
Status ShmUnit::AllocateMemoryForObject(...)
{
    // ...
    if (shmUnit == nullptr || shmUnit->size == 0) {
        LOG(ERROR) << "Error while allocating memory. "
                   << "Detail: code: [Out of memory], msg: [Shared memory no space in arena: 2]";
        return Status(K_NO_MEMORY, "Shared memory no space in arena: 2");
    }
    // ...
}
```

### B.2 Eviction 管理

**文件**: `worker_oc_eviction_manager.cpp:421-431`

```cpp
LOG(INFO) << "Eviction start.";
LOG(INFO) << "Evict is going on...";
// 尝试驱逐对象释放内存
```

### B.3 ZMQ RPC 指标定义

**文件**: `zmq_constants.h:172-188`

```cpp
uint64_t clientReqFrameworkNs = (clientSendTs > clientStartTs) ? (clientSendTs - clientStartTs) : 0U;
uint64_t clientRspFrameworkNs = (clientEndTs > clientRecvTs) ? (clientEndTs - clientRecvTs) : 0U;
uint64_t serverReqQueueNs = (serverExecStartTs > serverRecvTs) ? (serverExecStartTs - serverRecvTs) : 0U;
uint64_t serverExecNs = (serverExecEndTs > serverExecStartTs) ? (serverExecEndTs - serverExecStartTs) : 0U;
uint64_t serverRspQueueNs = (serverSendTs > serverExecEndTs) ? (serverSendTs - serverExecEndTs) : 0U;
```

---

## 附录 C：相关代码文件路径

| 文件 | 说明 |
|------|------|
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | Worker1 Get 请求处理 |
| `src/datasystem/worker/object_cache/service/worker_oc_service_batch_get_impl.cpp` | Remote Get 请求处理 |
| `src/datasystem/worker/object_cache/obj_cache_shm_unit.cpp` | 共享内存分配 |
| `src/datasystem/worker/object_cache/worker_oc_eviction_manager.cpp` | Eviction 管理 |
| `src/datasystem/common/rpc/zmq/zmq_constants.h` | ZMQ RPC 指标定义 |
