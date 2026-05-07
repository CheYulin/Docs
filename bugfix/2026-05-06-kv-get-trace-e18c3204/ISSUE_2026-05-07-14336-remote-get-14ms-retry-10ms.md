# Issue: RemoteGet 请求 14ms，疑似发生重试且间隔约 10ms

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | Remote Get / RPC |
| **影响节点** | 192.168.219.74 (worker2 / 数据节点) |
| **严重程度** | Medium |
| **Trace ID** | 14336_b9520999-c3db-47e7-a6f9-321f17ce8048 |

---

## 一、现象描述

Trace 14336 中，`ProcessGetObjectRequest` 总耗时 **14ms**（RemoteGet 延迟）。

**关键现象**：
1. worker1 发送 Remote get request 后，**14ms** 才完成
2. worker2 收到了 **2 次** `BatchGetObjectRemote request`，间隔约 **10ms**
3. 第一次请求 `remainingTime:13ms`，第二次 `remainingTime:3ms`
4. 第一次 URMA wait 耗时 **3.85ms**（异常偏高），第二次 **0.22ms**（正常）
5. 两次 URMA 状态都是 `[OK]`，说明 URMA 本身没有失败

**推测**：发生了 **RPC 重试**，间隔约 10ms（574ms 发送第一次请求，584ms 发送第二次请求）。

---

## 二、日志证据

### 2.1 worker1 日志（请求发送方）

```
worker_192.168.182.2: Remote get request:[batch] objects count[1], src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.182.2: Process Get done, clientId: a7ca70d8-5add-49bc-be47-2f191c90e948, objectKeys: kv_test_0_0_73132609913100_0, subTimeout: 0, get threads Statistics: idle(6),total(8),wait(0).The operations of worker Get exceed 3ms: {ProcessGetObjectRequest: 14 ms; }
```

**注意**：worker1 只打印了 **1 次** `Remote get request`，但 worker2 收到了 2 次请求。

### 2.2 worker2 日志（数据节点）

```
worker_192.168.219.74: BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73132609913100_0,,0,8388608) remainingTime:13ms, src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74: [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 3.85363ms, request id:216716, src address:192.168.219.74:31402, target address:192.168.182.2:31402, dataSize:8388608, cpuid:48, status: code: [OK], msg: [], urma_inflight_wr_count: 1, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA

worker_192.168.219.74: BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73132609913100_0,,0,8388608) remainingTime:3ms, src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74: [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.22495ms, request id:216717, src address:192.168.219.74:31402, target address:192.168.182.2:31402, dataSize:8388608, cpuid:35, status: code: [OK], msg: [], urma_inflight_wr_count: 1
```

**关键发现**：
1. worker2 收到了 **2 次请求**（request id: 216716 和 216717）
2. 第一次 `remainingTime:13ms`，第二次 `remainingTime:3ms`（明显更短）
3. 第一次 URMA wait 耗时 **3.85ms**（异常高），第二次 **0.22ms**（正常）
4. 两次 URMA status 都是 `[OK]`，说明 URMA 本身没有失败

### 2.3 时序分析（统一到 worker1 时钟）

假设 worker2 时钟比 worker1 快约 189ms（根据日志时间戳计算）：

| 时间 (worker1 时钟) | 事件 | 说明 |
|---------------------|------|------|
| 574ms | worker1 发送 Remote get request | 1 次请求 |
| ~574ms | worker2 收到第一次请求 (remainingTime:13ms) | worker2 时钟 385ms + 189ms 偏移 |
| 578ms | worker2 URMA wait 第一次完成 (3.85ms, id:216716) | 状态: [OK] |
| ~584ms | worker2 收到第二次请求 (remainingTime:3ms, id:216717) | worker2 时钟 395ms + 189ms 偏移 |
| 588ms | worker2 URMA wait 第二次完成 (0.22ms, id:216717) | 状态: [OK] |
| 574+14=588ms | worker1 ProcessGetObjectRequest 完成 (14ms) | 总耗时 |

---

## 三、根因分析

### 3.1 URMA 本身没有失败

从日志 `status: code: [OK]` 可以确认：
- URMA 数据传输本身是成功的
- 数据已经成功写入 worker1 的内存
- **问题不在 URMA 层面**

### 3.2 问题出在 RPC Response 层面

根据 `RetryOnErrorRepent` 代码（`worker_oc_service_batch_get_impl.cpp:609-625`），worker1 会在以下错误时自动重试：

```cpp
{ StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
  StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_URMA_CONNECT_FAILED, StatusCode::K_URMA_WAIT_TIMEOUT },
```

**推测根因链**：
1. 第一次 URMA wait 耗时 **3.85ms**（异常高，正常应 < 1ms）
2. 这导致整个 RPC 操作的 remainingTime 不够
3. worker1 侧触发了 **RPC 超时**或 **remainingTime 耗尽**
4. 触发 `RetryOnErrorRepent` **静默重试**
5. 第二次请求 remainingTime 只有 3ms（vs 第一次 13ms），证明重试发生

### 3.3 为什么日志里没有 vlog1 重试信息？

`RetryOnErrorRepent` 的重试是**静默的**——它只在重试次数用完或最终失败时才打印错误日志。重试本身不打印 vlog1。

---

## 四、结论

| 问题 | 答案 |
|------|------|
| RemoteGet 延迟多少？ | **14ms**（Remote get request 开始到完成） |
| 重试间隔多久？ | **约 10ms**（574ms 第一次请求，584ms 第二次请求） |
| URMA 失败了吗？ | **没有** - status=[OK]，数据已成功传输 |
| 异常是什么？ | **疑似 RPC 重试** - remainingTime 从 13ms 变成 3ms |

**根因推测**：RemoteGet 请求耗时 14ms，疑似发生重试且间隔约 10ms。第一次 URMA wait 耗时 3.85ms（偏高）可能导致 RPC 超时，触发 RetryOnErrorRepent 静默重试。

---

## 五、相关代码

### 5.1 RetryOnErrorRepent 重试逻辑

```cpp
// worker_oc_service_batch_get_impl.cpp:609-625
RETURN_IF_NOT_OK(RetryOnErrorRepent(
    timeoutMs,
    [&workerStub, &reqPb, &rspPb, &clientApi, &address, &payloads, this](int32_t) {
        PerfPoint point(PerfKey::WORKER_BATCH_REMOTE_GET_RPC);
        RETURN_IF_NOT_OK(workerStub->BatchGetObjectRemote(&clientApi));
        RETURN_IF_NOT_OK(workerStub->BatchGetObjectRemoteWrite(clientApi, reqPb));
        auto rc = clientApi->Read(rspPb);
        RETURN_IF_NOT_OK(TryReconnectRemoteWorker(address, rc));
        RETURN_IF_NOT_OK(clientApi->ReceivePayload(payloads));
        return Status::OK();
    },
    []() { return Status::OK(); },
    { StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
      StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_URMA_CONNECT_FAILED, StatusCode::K_URMA_WAIT_TIMEOUT },
    minRetryOnceRpcMs));
```

### 5.2 URMA Wait 逻辑

```cpp
// urma_manager.cpp:829
Status UrmaManager::WaitToFinish(uint64_t requestId, int64_t timeoutMs)
{
    Timer timer;
    Status waitRc = event->WaitFor(std::chrono::milliseconds(timeoutMs));
    auto elapsedMs = timer.ElapsedMilliSecond();
    VLOG(vlogLevel) << "[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost "
                    << elapsedMs << "ms, request id:" << requestId
                    << ", ... status: " << waitRc.ToString() << ...;
}
```

---

## 六、建议

1. **降低 URMA wait 延迟告警阈值**
   - 当前阈值：1ms
   - 建议阈值：0.5ms

2. **调查 worker2 (192.168.219.74) 的 URMA 性能问题**
   - 为什么 URMA write 延迟异常高（3.85ms）
   - 检查 URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY 日志

3. **考虑增加 RPC 超时时间**
   - 或减少 URMA 异常对整体延迟的影响

4. **增加重试日志**
   - 在 `RetryOnErrorRepent` 中增加 vlog1 日志，便于追踪重试行为

---

## 七、其他受影响 Trace

| Trace ID | URMA Wait (ms) | QueryMeta (ms) | PG (ms) | 问题类型 |
|----------|----------------|----------------|---------|----------|
| 14336 | 3.85 + 0.22 | 0.31 | 14 | URMA 延迟高 + RPC 重试 |
| 10652 | 0.88 | 0.39 | 15 | URMA 延迟偏高 |
| 3661 | 0.06 | 2.17 | 12 | QueryMeta 延迟高 |
| 5067 | 0.06 | 2.27 | 12 | QueryMeta 延迟高 |

---

## 八、全量日志

### Trace 14336 全量日志文件

**日志文件路径**: `/tmp/trace_extract/tmp/14336_b9520999-c3db-47e7-a6f9-321f17ce8048.log`

**全量日志内容**:

```
SDK_192.168.182.9/ds_client_access_1160.log:2026-05-07T01:49:46.587992 | I | access_recorder.cpp:182 | kvc-jingpai-client-bf8d49dbb-lkwkh | 1160:1228 | b9520999-c3db-47e7-a6f9-321f17ce8048 |  | 0 | DS_KV_CLIENT_GET | 14336 | 8388608 | {Object_key:kv_test_0_0_73132609913100_0,timeout:0,transportType:SHM} | 
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:49:46.573836 | I | worker_oc_service_get_impl.cpp:130 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:291 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Get start from client:a7ca70d8-5add-49bc-be47-2f191c90e948 server api read elapsed ms: 0.0055 inflight remote get request count: 0
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:49:46.573858 | I | worker_oc_service_get_impl.cpp:165 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:207 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Process Get from client: a7ca70d8-5add-49bc-be47-2f191c90e948, objects: kv_test_0_0_73132609913100_0, get threads Statistics: idle(7),total(8),wait(0), elapsed ms: 0, remainingTime: 16
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:49:46.573882 | I | worker_oc_service_get_impl.cpp:1749 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:207 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Query metadata from master: 192.168.210.194:31402, objects: kv_test_0_0_73132609913100_0, request id: 91f72568-5bc8-4a79-8930-449eff071815, remainingTime:14ms
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:49:46.574183 | I | worker_oc_service_get_impl.cpp:778 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:207 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Query meta success: target num 1, success num 1, elapsed 0.310 ms
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:49:46.574207 | I | worker_oc_service_batch_get_impl.cpp:607 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:207 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Remote get request:[batch] objects count[1], src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.182.2/datasystem_worker.INFO.log:2026-05-07T01:49:46.587870 | I | worker_oc_service_get_impl.cpp:193 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:207 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Process Get done, clientId: a7ca70d8-5add-49bc-be47-2f191c90e948, objectKeys: kv_test_0_0_73132609913100_0, subTimeout: 0, get threads Statistics: idle(6),total(8),wait(0).The operations of worker Get exceed 3ms: {ProcessGetObjectRequest: 14 ms; }
worker_192.168.182.2/access.log:2026-05-07T01:49:46.587859 | I | access_recorder.cpp:182 | kvc-jingpai-worker-6c6dd44d6d-kwvvc | 11:207 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai | 0 | DS_POSIX_GET | 14028 | 8388608 | {Object_key:kv_test_0_0_73132609913100_0,count:1,sub_timeout:0} | 
worker_192.168.210.194/datasystem_worker.INFO.log:2026-05-07T01:49:46.578807 | I | master_oc_service_impl.cpp:261 | kvc-jingpai-worker-6c6dd44d6d-7j6cp | 11:281 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Processing QueryMetaReq, requestId: 91f72568-5bc8-4a79-8930-449eff071815
worker_192.168.210.194/datasystem_worker.INFO.log:2026-05-07T01:49:46.578819 | I | master_oc_service_impl.cpp:270 | kvc-jingpai-worker-6c6dd44d6d-7j6cp | 11:281 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  QueryMeta on master 192.168.182.2:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.385623 | I | worker_worker_oc_service_impl.cpp:693 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:300 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73132609913100_0,,0,8388608) remainingTime:13ms, src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.385635 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:300 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Processing pull object[kv_test_0_0_73132609913100_0] offset[0] size[8388608], src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.385655 | I | urma_manager.cpp:1297 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:300 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  URMA write useNumaAffinity:1src:1, dst:1, jetty id:1031, urma_inflight_wr_count:1
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.389533 | I | urma_manager.cpp:852 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:300 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 3.85363ms, request id:216716, src address:192.168.219.74:31402, target address:192.168.182.2:31402, dataSize:8388608, cpuid:48, status: code: [OK], msg: [], urma_inflight_wr_count: 1, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.395458 | I | worker_worker_oc_service_impl.cpp:693 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73132609913100_0,,0,8388608) remainingTime:3ms, src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.395472 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  Processing pull object[kv_test_0_0_73132609913100_0] offset[0] size[8388608], src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.395491 | I | urma_manager.cpp:1297 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  URMA write useNumaAffinity:1src:1, dst:1, jetty id:1031, urma_inflight_wr_count:1
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:49:46.395752 | I | urma_manager.cpp:852 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | b9520999-c3db-47e7-a6f9-321f17ce8048 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.22495ms, request id:216717, src address:192.168.219.74:31402, target address:192.168.182.2:31402, dataSize:8388608, cpuid:35, status: code: [OK], msg: [], urma_inflight_wr_count: 1, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA
```

### 日志说明

| # | 时间戳 | 节点 | 事件 |
|---|--------|------|------|
| 1 | 01:49:46.587992 | Client (192.168.182.9) | DS_KV_CLIENT_GET, transportType:SHM |
| 2 | 01:49:46.573836 | worker1 (192.168.182.2) | Get start from client |
| 3 | 01:49:46.573858 | worker1 (192.168.182.2) | Process Get, remainingTime: 16ms |
| 4 | 01:49:46.573882 | worker1 (192.168.182.2) | Query metadata from master (192.168.210.194) |
| 5 | 01:49:46.574183 | worker1 (192.168.182.2) | Query meta success, elapsed 0.310ms |
| 6 | 01:49:46.574207 | worker1 (192.168.182.2) | **Remote get request** (1 object -> 192.168.219.74) |
| 7 | 01:49:46.587870 | worker1 (192.168.182.2) | **Process Get done, PG: 14ms** |
| 8 | 01:49:46.587859 | worker1 (192.168.182.2) | DS_POSIX_GET access log |
| 9 | 01:49:46.578807 | master (192.168.210.194) | Processing QueryMetaReq |
| 10 | 01:49:46.578819 | master (192.168.210.194) | QueryMeta success |
| 11 | 01:49:46.385623 | worker2 (192.168.219.74) | **第一次 BatchGetObjectRemote request**, remainingTime:13ms |
| 12 | 01:49:46.385635 | worker2 (192.168.219.74) | Processing pull object |
| 13 | 01:49:46.385655 | worker2 (192.168.219.74) | URMA write, jetty id:1031 |
| 14 | 01:49:46.389533 | worker2 (192.168.219.74) | **URMA wait 第一次完成: 3.85ms**, id:216716, status:[OK] |
| 15 | 01:49:46.395458 | worker2 (192.168.219.74) | **第二次 BatchGetObjectRemote request**, remainingTime:3ms |
| 16 | 01:49:46.395472 | worker2 (192.168.219.74) | Processing pull object (重试) |
| 17 | 01:49:46.395491 | worker2 (192.168.219.74) | URMA write, jetty id:1031 |
| 18 | 01:49:46.395752 | worker2 (192.168.219.74) | **URMA wait 第二次完成: 0.22ms**, id:216717, status:[OK] |

**注意**：worker2 的时间戳 (01:49:46.385xxx) 早于 worker1 的时间戳 (01:49:46.573xxx)，这是因为 worker2 的系统时钟比 worker1 快约 189ms。如果统一到 worker1 时钟：
- worker2 收到第一次请求：385 + 189 = 574ms
- worker2 收到第二次请求：395 + 189 = 584ms
