# Issue: URMA Wait 延迟异常高导致 Remote Get 延迟增加

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | URMA (Unified RDMA Memory Access) |
| **影响节点** | 192.168.219.74 (worker2 / 数据节点) |
| **严重程度** | Medium |
| **涉及 Trace** | 14336, 10652 |

---

## 一、现象描述

URMA Wait 延迟异常高（正常应 < 1ms），导致 ProcessGetObjectRequest 总时间偏长。

**关键现象**：
1. Trace 14336: URMA Wait 耗时 **3.85ms**（异常偏高），发生 RPC 重试
2. Trace 10652: URMA Wait 耗时 **3.78ms**（异常偏高），未发生明显重试
3. URMA 状态都是 `[OK]`，说明 URMA 本身没有失败

---

## 二、日志证据

### 2.1 Trace 14336 日志

```
worker_192.168.182.2: Query meta success: elapsed 0.310 ms
worker_192.168.182.2: Remote get request:[batch] objects count[1], src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.182.2: Process Get done, clientId: ..., objectKeys: kv_test_0_0_73132609913100_0, subTimeout: 0, ...{ProcessGetObjectRequest: 14 ms; }

worker_192.168.219.74: BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73132609913100_0,,0,8388608) remainingTime:13ms, src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74: URMA write useNumaAffinity:1src:1, dst:1, jetty id:1031, urma_inflight_wr_count:1
worker_192.168.219.74: [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 3.85363ms, request id:216716, src address:192.168.219.74:31402, target address:192.168.182.2:31402, dataSize:8388608, cpuid:48, status: code: [OK], msg: [], urma_inflight_wr_count: 1

worker_192.168.219.74: BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73132609913100_0,,0,8388608) remainingTime:3ms, src=192.168.182.2:31402, dst=192.168.219.74:31402
worker_192.168.219.74: [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.22495ms, request id:216717, src address:192.168.219.74:31402, target address:192.168.182.2:31402, dataSize:8388608, cpuid:35, status: code: [OK], msg: [], urma_inflight_wr_count: 1
```

### 2.2 Trace 10652 日志

```
worker_192.168.168.193: Query meta success: elapsed 0.341 ms
worker_192.168.168.193: Remote get request:[batch] objects count[1], src=192.168.168.193:31402, dst=192.168.219.74:31402
worker_192.168.168.193: Process Get done, clientId: ..., objectKeys: kv_test_0_0_73199507818790_0, subTimeout: 0, ...{ProcessGetObjectRequest: 10 ms; }

worker_192.168.219.74: BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73199507818790_0,,0,8388608) remainingTime:13ms, src=192.168.168.193:31402, dst=192.168.219.74:31402
worker_192.168.219.74: URMA write useNumaAffinity:1src:1, dst:1, jetty id:1047, urma_inflight_wr_count:1
worker_192.168.219.74: [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 3.78157ms, request id:222149, src address:192.168.219.74:31402, target address:192.168.168.193:31402, dataSize:8388608, cpuid:35, status: code: [OK], msg: [], urma_inflight_wr_count: 1
```

### 2.3 关键发现

| 发现 | Trace 14336 | Trace 10652 |
|------|-------------|-------------|
| URMA Wait 延迟 | 3.85ms + 0.22ms | 3.78ms |
| remainingTime 变化 | 14→13→3 | 14→13 |
| URMA Status | [OK], [OK] | [OK] |
| 是否发生重试 | **是** | 否（未明显触发） |

---

## 三、根因分析

### 3.1 URMA 本身没有失败

从日志 `status: code: [OK]` 可以确认：
- URMA 数据传输本身是成功的
- 数据已经成功写入 worker1 的内存
- **问题不在 URMA 层面**

### 3.2 问题出在 RPC Response 层面

根据 `RetryOnErrorRepent` 代码，worker1 会在以下错误时自动重试：

```cpp
{ StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
  StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_URMA_CONNECT_FAILED, StatusCode::K_URMA_WAIT_TIMEOUT },
```

### 3.3 Trace 14336 URMA Wait 延迟详细分析

**时间分解（以 worker1 时钟为基准，worker2 时钟快 189ms）**：

#### 第一次请求

| 时间 (worker1 时钟) | 事件 | 说明 |
|---------------------|------|------|
| 01:49:46.574 | worker1 发送 Remote get request | |
| 01:49:46.574 | worker2 收到第一次请求 | (worker2:385ms + 189ms偏移) |
| 01:49:46.574 | worker2 URMA write 开始 | |
| 01:49:46.578 | worker2 URMA wait 完成 | **耗时 3.88ms (异常高)** |

#### 第二次请求（重试）

| 时间 (worker1 时钟) | 事件 | 说明 |
|---------------------|------|------|
| 01:49:46.584 | worker2 收到第二次请求 | (worker2:395ms + 189ms偏移) |
| 01:49:46.584 | worker2 URMA write 开始 | |
| 01:49:46.588 | worker2 URMA wait 完成 | **耗时 0.26ms (正常)** |

**URMA Wait 延迟对比**：

| 请求 | URMA Wait 耗时 | CPU ID | 是否正常 |
|------|---------------|--------|----------|
| 第一次 | **3.88ms** | 48 | **异常高** |
| 第二次 | 0.26ms | 35 | 正常 |

**关键发现**：两次请求在不同 CPU 上执行（48 vs 35），可能是 CPU 调度或缓存问题导致第一次延迟高。

### 3.4 Trace 10652 URMA Wait 分析

| 时间 | 事件 | 说明 |
|------|------|------|
| 01:50:53.289 | worker2 收到请求 | worker2 时钟 |
| 01:50:53.289 | URMA write 开始 | |
| 01:50:53.293 | URMA wait 完成 | **耗时 3.78ms (异常高)** |

**对比正常 trace**：

| Trace | URMA Wait | 说明 |
|-------|-----------|------|
| 14336 (第一次) | 3.88ms | 异常 |
| 14336 (第二次) | 0.26ms | 正常 |
| 10652 | 3.78ms | 异常 |
| 3661 | 0.18ms | 正常 |

### 3.5 URMA Wait 延迟可能原因

根据日志中的 suggest 提示：
> "check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window"

可能原因：
1. **CPU 调度延迟**：第一次请求在 CPU 48，第二次在 CPU 35
2. **URMA 队列阻塞**：上一次 URMA 操作未完成导致等待
3. **网络设备负载**：RDMA 网卡处理延迟
4. **NUMA 跨区域访问**：虽然 useNumaAffinity 显示 src:1, dst:1（同节点）

### 3.6 重试间隔分析

| Trace | 重试间隔 | 说明 |
|-------|----------|------|
| 14336 | **10ms** | 574ms -> 584ms |
| 10652 | 无重试 | remainingTime 刚好够用 |

**重试间隔 10ms** 符合 RPC 超时重试的典型行为。

---

## 四、结论

| 问题 | 答案 |
|------|------|
| URMA 失败了吗？ | **没有** - status=[OK]，数据已成功传输 |
| 为什么延迟高？ | **URMA wait 耗时过长（3.78~3.85ms）** - 正常应 < 1ms |
| 触发重试了吗？ | Trace 14336 触发重试（remainingTime: 14→3ms）；10652 未触发 |
| 根因 | **192.168.219.74 (worker2) 的 URMA 性能异常** |

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

1. **调查 192.168.219.74 的 URMA 性能问题**
   - 为什么 URMA wait 延迟异常高（3.78~3.85ms）
   - 检查 URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY 日志

2. **降低 URMA wait 延迟告警阈值**
   - 当前阈值：1ms
   - 建议阈值：0.5ms

3. **增加重试日志**
   - 在 `RetryOnErrorRepent` 中增加 vlog1 日志，便于追踪重试行为

---

## 七、全量日志

### Trace 14336 全量日志

**日志文件路径**: `/tmp/trace_extract/tmp/14336_b9520999-c3db-47e7-a6f9-321f17ce8048.log`

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

### Trace 10652 全量日志

**日志文件路径**: `/tmp/trace_extract/tmp/10652_dcee9c9b-9428-43a5-8559-8263a32a9401.log`

```
SDK_192.168.168.198/ds_client_access_1160.log:2026-05-07T01:50:53.401265 | I | access_recorder.cpp:182 | kvc-jingpai-client-bf8d49dbb-l7vzg | 1160:1305 | dcee9c9b-9428-43a5-8559-8263a32a9401 |  | 0 | DS_KV_CLIENT_GET | 10652 | 8388608 | {Object_key:kv_test_0_0_73199507818790_0,timeout:0,transportType:SHM} | 
worker_192.168.168.193/datasystem_worker.INFO.log:2026-05-07T01:50:53.390759 | I | worker_oc_service_get_impl.cpp:130 | kvc-jingpai-worker-6c6dd44d6d-qbc2h | 11:296 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Get start from client:15bb19b4-f51f-4adf-8dcf-f445973e35d7 server api read elapsed ms: 0.00639 inflight remote get request count: 0
worker_192.168.168.193/datasystem_worker.INFO.log:2026-05-07T01:50:53.390782 | I | worker_oc_service_get_impl.cpp:165 | kvc-jingpai-worker-6c6dd44d6d-qbc2h | 11:206 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Process Get from client: 15bb19b4-f51f-4adf-8dcf-f445973e35d7, objects: kv_test_0_0_73199507818790_0, get threads Statistics: idle(7),total(8),wait(0), elapsed ms: 0, remainingTime: 16
worker_192.168.168.193/datasystem_worker.INFO.log:2026-05-07T01:50:53.390812 | I | worker_oc_service_get_impl.cpp:1749 | kvc-jingpai-worker-6c6dd44d6d-qbc2h | 11:206 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Query metadata from master: 192.168.89.10:31402, objects: kv_test_0_0_73199507818790_0, request id: a3e43e34-be23-4629-afe9-6fb23beaa65b, remainingTime:14ms
worker_192.168.168.193/datasystem_worker.INFO.log:2026-05-07T01:50:53.391142 | I | worker_oc_service_get_impl.cpp:778 | kvc-jingpai-worker-6c6dd44d6d-qbc2h | 11:206 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Query meta success: target num 1, success num 1, elapsed 0.341 ms
worker_192.168.168.193/datasystem_worker.INFO.log:2026-05-07T01:50:53.391169 | I | worker_oc_service_batch_get_impl.cpp:607 | kvc-jingpai-worker-6c6dd44d6d-qbc2h | 11:206 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Remote get request:[batch] objects count[1], src=192.168.168.193:31402, dst=192.168.219.74:31402
worker_192.168.168.193/datasystem_worker.INFO.log:2026-05-07T01:50:53.401172 | I | worker_oc_service_get_impl.cpp:193 | kvc-jingpai-worker-6c6dd44d6d-qbc2h | 11:206 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Process Get done, clientId: 15bb19b4-f51f-4adf-8dcf-f445973e35d7, objectKeys: kv_test_0_0_73199507818790_0, subTimeout: 0, get threads Statistics: idle(7),total(8),wait(0).The operations of worker Get exceed 3ms: {ProcessGetObjectRequest: 10 ms; }
worker_192.168.168.193/access.log:2026-05-07T01:50:53.401154 | I | access_recorder.cpp:182 | kvc-jingpai-worker-6c6dd44d6d-qbc2h | 11:206 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai | 0 | DS_POSIX_GET | 10400 | 8388608 | {Object_key:kv_test_0_0_73199507818790_0,count:1,sub_timeout:0} | 
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:50:53.289682 | I | worker_worker_oc_service_impl.cpp:693 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  BatchGetObjectRemote request (objectKey, requestId, readOffset, readSize): (kv_test_0_0_73199507818790_0,,0,8388608) remainingTime:13ms, src=192.168.168.193:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:50:53.289707 | I | worker_worker_oc_service_impl.cpp:196 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Processing pull object[kv_test_0_0_73199507818790_0] offset[0] size[8388608], src=192.168.168.193:31402, dst=192.168.219.74:31402
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:50:53.289745 | I | urma_manager.cpp:1297 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  URMA write useNumaAffinity:1src:1, dst:1, jetty id:1047, urma_inflight_wr_count:1
worker_192.168.219.74/datasystem_worker.INFO.log:2026-05-07T01:50:53.293575 | I | urma_manager.cpp:852 | kvc-jingpai-worker-6c6dd44d6d-5pccf | 11:302 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 3.78157ms, request id:222149, src address:192.168.219.74:31402, target address:192.168.168.193:31402, dataSize:8388608, cpuid:35, status: code: [OK], msg: [], urma_inflight_wr_count: 1, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA
worker_192.168.89.10/datasystem_worker.INFO.log:2026-05-07T01:50:53.389843 | I | master_oc_service_impl.cpp:261 | kvc-jingpai-worker-6c6dd44d6d-c6q4p | 11:268 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  Processing QueryMetaReq, requestId: a3e43e34-be23-4629-afe9-6fb23beaa65b
worker_192.168.89.10/datasystem_worker.INFO.log:2026-05-07T01:50:53.389859 | I | master_oc_service_impl.cpp:270 | kvc-jingpai-worker-6c6dd44d6d-c6q4p | 11:268 | dcee9c9b-9428-43a5-8559-8263a32a9401 | jingpai |  QueryMeta on master 192.168.168.193:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
```

### 日志说明 (Trace 14336)

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

**注意**：worker2 的时间戳 (01:49:46.385xxx) 早于 worker1 的时间戳 (01:49:46.573xxx)，这是因为 worker2 的系统时钟比 worker1 快约 188ms。如果统一到 worker1 时钟：
- worker2 收到第一次请求：385 + 188 = 573ms
- worker2 收到第二次请求：395 + 188 = 583ms
