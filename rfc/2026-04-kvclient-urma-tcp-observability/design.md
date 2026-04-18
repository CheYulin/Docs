# KVClient 可观测与可靠性：问题分析与代码修改计划

本文梳理当前 KVClient（MCreate / MSet / MGet）调用链中 TCP、URMA 相关的可观测与可靠性问题，给出根因分析、代码修改建议和优先级。

**仓库**：`yuanrong-datasystem`

---

## 问题总表

| 编号 | 问题 | 优先级 | 影响 | 涉及文件 |
|------|------|--------|------|---------|
| P1 | URMA wait 超时返回 `K_RPC_DEADLINE_EXCEEDED` 而非 URMA 专用码 | **P0** | 定界混淆 + 重试策略错误 | `rdma_util.h`, `urma_manager.cpp` |
| P2 | ZMQ `TRY_AGAIN` 被改写为 `K_RPC_UNAVAILABLE(1002)` | **P1** | 1002 成为桶码，定界困难 | `zmq_msg_queue.h`, `zmq_stub_impl.h` |
| P3 | `CheckUrmaConnectionStable` 无 WARNING/ERROR 日志 | **P1** | 无法定位重连触发时刻 | `urma_manager.cpp` |
| P4 | `ServerEventHandleThreadMain` 忽略 `PollJfcWait` 错误返回 | **P1** | 隐藏 URMA 异常 | `urma_manager.cpp` |
| P5 | URMA 事件处理缺乏连接/操作上下文 | **P2** | Trace 无法跨 Worker 串联 | `urma_manager.cpp` |
| P6 | 1002 桶码未做子分类 | **P2** | TCP 问题定界困难 | `zmq_msg_queue.h`, `zmq_stub_conn.cpp`, `unix_sock_fd.cpp` |
| P7 | JFS 重建缺乏 metrics 和详细日志 | **P2** | 无法追踪重建频率趋势 | `urma_manager.cpp` |
| P8 | 性能 Metrics 缺口补充 | **P2** | 端到端可观测不完整 | 多文件 |
| P9 | URMA 关键操作缺乏 Trace 上下文 | **P2** | 难以跨 Worker 串联请求 | `urma_manager.cpp` |

---

## P1：URMA wait 超时返回 `K_RPC_DEADLINE_EXCEEDED` — 需新增 `K_URMA_WAIT_TIMEOUT`

### 现状分析

`Event::WaitFor` 是 URMA 数据面的核心等待机制：当 worker 发起 `ds_urma_write` 后，通过 `WaitToFinish` → `Event::WaitFor` 等待 `ServerEventHandleThreadMain` 线程 poll 到完成事件并 `NotifyAll`。

**当前代码**（`rdma_util.h:91-100`）：

```cpp
Status WaitFor(std::chrono::milliseconds timeout)
{
    std::unique_lock<std::mutex> lock(eventMutex_);
    bool gotNotification = cv_.wait_for(lock, timeout, [this] { return ready_; });
    if (!gotNotification && !ready_) {
        RETURN_STATUS_LOG_ERROR(K_RPC_DEADLINE_EXCEEDED,                  // ← 问题所在
                                FormatString("Timed out waiting for request: %d", requestId_));
    }
    return Status::OK();
}
```

**同样问题存在于**：
- `EventWaiter::WaitAny`（`rdma_util.h:66-75`）— 同样返回 `K_RPC_DEADLINE_EXCEEDED`
- `UrmaManager::WaitToFinish`（`urma_manager.cpp:697`）— 前置超时检查也返回 `K_RPC_DEADLINE_EXCEEDED`

**影响**：
1. 值班人员看到 `1001`（`K_RPC_DEADLINE_EXCEEDED`）首先怀疑 RPC/TCP 超时，实际根因是 URMA 完成事件未到达
2. 外层 `RetryOnError` 对 `1001` 按 RPC 超时策略重试，但 URMA 超时可能需要走 `TryReconnectRemoteWorker`（1006 路径）
3. 与 `PollJfcWait` 中 `ds_urma_wait_jfc` 返回 `K_URMA_ERROR` 的语义不一致

### 修改方案

**Step 1：新增错误码 `K_URMA_WAIT_TIMEOUT`**

文件：`src/datasystem/common/util/status_code.def`

```diff
 // rdma
 STATUS_CODE_DEF(K_OC_REMOTE_GET_NOT_ENOUGH, "Size on the remote node has changed")
 STATUS_CODE_DEF(K_URMA_ERROR, "Urma operation failed")
 STATUS_CODE_DEF(K_URMA_NEED_CONNECT, "Urma needs to reconnet")
 STATUS_CODE_DEF(K_RDMA_NEED_CONNECT, "Rdma needs to reconnet")
 STATUS_CODE_DEF(K_URMA_TRY_AGAIN, "Urma operation failed, try again")
 STATUS_CODE_DEF(K_URMA_CONNECT_FAILED, "Urma connect failed")
+STATUS_CODE_DEF(K_URMA_WAIT_TIMEOUT, "Urma wait for completion timed out")
```

**Step 2：修改 `Event::WaitFor`**

文件：`src/datasystem/common/rdma/rdma_util.h`

```diff
     Status WaitFor(std::chrono::milliseconds timeout)
     {
         std::unique_lock<std::mutex> lock(eventMutex_);
         bool gotNotification = cv_.wait_for(lock, timeout, [this] { return ready_; });
         if (!gotNotification && !ready_) {
-            RETURN_STATUS_LOG_ERROR(K_RPC_DEADLINE_EXCEEDED,
-                                    FormatString("Timed out waiting for request: %d", requestId_));
+            RETURN_STATUS_LOG_ERROR(K_URMA_WAIT_TIMEOUT,
+                                    FormatString("[URMA_WAIT_TIMEOUT] Timed out waiting for request: %d", requestId_));
         }
         return Status::OK();
     }
```

**Step 3：修改 `EventWaiter::WaitAny`**

同文件 `rdma_util.h`：

```diff
     Status WaitAny(std::chrono::milliseconds timeout, std::shared_ptr<Event> &event)
     {
         std::unique_lock<std::mutex> lock(mtx_);
         if (!cv_.wait_for(lock, timeout, [&] { return !ready_.empty(); })) {
-            RETURN_STATUS_LOG_ERROR(K_RPC_DEADLINE_EXCEEDED, FormatString("Timed out waiting for any event"));
+            RETURN_STATUS_LOG_ERROR(K_URMA_WAIT_TIMEOUT,
+                                    FormatString("[URMA_WAIT_TIMEOUT] Timed out waiting for any event"));
         }
         event = ready_.front();
         ready_.pop();
         return Status::OK();
     }
```

**Step 4：修改 `WaitToFinish` 前置超时检查**

文件：`src/datasystem/common/rdma/urma_manager.cpp`

```diff
 Status UrmaManager::WaitToFinish(uint64_t requestId, int64_t timeoutMs)
 {
     PerfPoint point(PerfKey::URMA_WAIT_TO_FINISH);
     INJECT_POINT("UrmaManager.UrmaWaitError",
-                 []() { return Status(K_RPC_DEADLINE_EXCEEDED, "Injcect urma wait error"); });
+                 []() { return Status(K_URMA_WAIT_TIMEOUT, "Inject urma wait error"); });
     if (timeoutMs < 0) {
-        RETURN_STATUS_LOG_ERROR(K_RPC_DEADLINE_EXCEEDED, FormatString("timedout waiting for request: %d", requestId_));
+        RETURN_STATUS_LOG_ERROR(K_URMA_WAIT_TIMEOUT,
+                                FormatString("[URMA_WAIT_TIMEOUT] timedout waiting for request: %d", requestId_));
     }
```

**Step 5：外层重试集合适配**

`K_URMA_WAIT_TIMEOUT` 应被 worker 侧远端拉取的 `RetryOnError` 重试集合识别。

文件：`src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp`

```diff
             { StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
-              StatusCode::K_RPC_UNAVAILABLE }, minRetryOnceRpcMs);
+              StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_URMA_WAIT_TIMEOUT }, minRetryOnceRpcMs);
```

文件：`src/datasystem/worker/object_cache/service/worker_oc_service_batch_get_impl.cpp`

```diff
                   StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_URMA_CONNECT_FAILED },
+                  StatusCode::K_URMA_WAIT_TIMEOUT },
                   minRetryOnceRpcMs));
```

---

## P2：ZMQ `TRY_AGAIN` 改写为 `K_RPC_UNAVAILABLE(1002)` — 分析与建议

### 现状分析

**改写发生在两个地方**：

**位置 A：`zmq_msg_queue.h:881-894` — `ClientReceiveMsg`**

```cpp
Status ClientReceiveMsg(R &ele, ZmqRecvFlags flags)
{
    Status rc = ReceiveMsg(ele, flags);
    if (rc.GetCode() == K_TRY_AGAIN) {
        if (flags == ZmqRecvFlags::DONTWAIT) {
            return rc;  // 非阻塞调用保留 TRY_AGAIN
        }
        rc = Status(StatusCode::K_RPC_UNAVAILABLE,
                    FormatString("Rpc service for client %s has not responded within the allowed time. Detail: %s",
                                 GetId(), rc.ToString()));
    }
    return rc;
}
```

**位置 B：`zmq_stub_impl.h:138-148`**

```cpp
if (rc.GetCode() == K_TRY_AGAIN) {
    if (flags == ZmqRecvFlags::DONTWAIT) {
        return rc;
    }
    rc = Status(StatusCode::K_RPC_UNAVAILABLE, rc.GetMsg());
    LOG(WARNING) << "Rpc service for client " << clientId << " has not responded within the allowed time.";
    mQue->Close();
    Remove(tagId);
}
```

**为什么要改写**：
1. ZMQ 底层的 `TRY_AGAIN` 含义是"消息队列已满/对端未响应，请稍后重试"
2. 对于阻塞模式（非 `DONTWAIT`），ZMQ 已经等到了内部超时（队列收发超时），此时 `TRY_AGAIN` 实际含义已经变成了"服务不可用"
3. 设计者认为暴露 `TRY_AGAIN` 给上层会被误认为"可以立刻重试"，实际连接可能已经处于不健康状态

**问题**：
改写后 `1002` 成为了"桶码"，同时覆盖了以下根因（见 `定位定界-故障树-代码证据与告警设计.md` §2.2）：
- ZMQ 队列等回复超时 → `1002`（改写自 `TRY_AGAIN`）
- socket ECONNRESET/EPIPE → `1002`（`unix_sock_fd.cpp:ErrnoToStatus`）
- fd 交换失败 → `1002`（`client_worker_common_api.cpp:318`）
- 建连超时 → `1002`（`zmq_stub_conn.cpp:1500`）
- 心跳不可写 → `1002`（`zmq_stub_conn.cpp:264`）

### 修改方案

**不改变错误码本身**（改动影响面太大），而是**在日志消息中增加子分类前缀**，便于日志聚合和自动分流：

**Step 1：`zmq_msg_queue.h` 增加子分类前缀**

```diff
         rc = Status(StatusCode::K_RPC_UNAVAILABLE,
-                    FormatString("Rpc service for client %s has not responded within the allowed time. Detail: %s",
+                    FormatString("[RPC_RECV_TIMEOUT] Rpc service for client %s has not responded within the allowed time. Detail: %s",
                                  GetId(), rc.ToString()));
```

**Step 2：`zmq_stub_impl.h` 增加前缀**

```diff
         rc = Status(StatusCode::K_RPC_UNAVAILABLE, rc.GetMsg());
-        LOG(WARNING) << "Rpc service for client " << clientId << " has not responded within the allowed time.";
+        LOG(WARNING) << "[RPC_RECV_TIMEOUT] Rpc service for client " << clientId
+                     << " has not responded within the allowed time.";
```

**Step 3：`unix_sock_fd.cpp` 现有的 `Connect reset` 已可区分，确认格式一致**

当前已有 `Connect reset. fd %d. err %s`，建议统一加前缀：

```diff
-        RETURN_STATUS(StatusCode::K_RPC_UNAVAILABLE, FormatString("Connect reset. fd %d. err %s", fd, StrErr(err)));
+        RETURN_STATUS(StatusCode::K_RPC_UNAVAILABLE,
+                      FormatString("[TCP_CONN_RESET] Connect reset. fd %d. err %s", fd, StrErr(err)));
```

**Step 4：`zmq_stub_conn.cpp` 中各个 1002 返回点增加子分类**

```diff
 // 心跳不可写
-CHECK_FAIL_RETURN_STATUS(events & ZMQ_POLLOUT, K_RPC_UNAVAILABLE, "Network unreachable");
+CHECK_FAIL_RETURN_STATUS(events & ZMQ_POLLOUT, K_RPC_UNAVAILABLE, "[TCP_NETWORK_UNREACHABLE] Network unreachable");

 // 建连超时
-CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(success, K_RPC_UNAVAILABLE, "Timeout waiting for SockConnEntry wait");
+CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(success, K_RPC_UNAVAILABLE,
+                                     "[TCP_CONN_TIMEOUT] Timeout waiting for SockConnEntry wait");

 // 服务不可用
-RETURN_STATUS(K_RPC_UNAVAILABLE, FormatString("Remote service is not available within allowable %d ms", timeout));
+RETURN_STATUS(K_RPC_UNAVAILABLE,
+              FormatString("[TCP_SERVICE_UNAVAILABLE] Remote service is not available within allowable %d ms", timeout));
```

**Step 5：`client_worker_common_api.cpp` fd 交换失败**

```diff
-return { StatusCode::K_RPC_UNAVAILABLE, "Can not create connection to worker for shm fd transfer." };
+return { StatusCode::K_RPC_UNAVAILABLE, "[SHM_FD_TRANSFER_FAILED] Can not create connection to worker for shm fd transfer." };
```

**子分类前缀汇总**（可用于日志规则聚合）：

| 前缀 | 含义 | 原始根因 |
|------|------|---------|
| `[RPC_RECV_TIMEOUT]` | ZMQ 收消息超时（改写自 TRY_AGAIN） | ZMQ 队列超时 |
| `[TCP_CONN_RESET]` | socket 连接被重置 | ECONNRESET/EPIPE |
| `[TCP_CONN_TIMEOUT]` | TCP/UDS 建连超时 | connect 超时 |
| `[TCP_NETWORK_UNREACHABLE]` | 心跳时网络不可达 | ZMQ_POLLOUT 失败 |
| `[TCP_SERVICE_UNAVAILABLE]` | 远端服务在允许时间内不可用 | 超时 |
| `[SHM_FD_TRANSFER_FAILED]` | UDS fd 交换失败 | UDS connect 失败 |

---

## P3：`CheckUrmaConnectionStable` 缺乏日志

### 现状分析

**当前代码**（`urma_manager.cpp:1292-1307`）：

```cpp
Status UrmaManager::CheckUrmaConnectionStable(const std::string &hostAddress, const std::string &instanceId)
{
    TbbUrmaConnectionMap::const_accessor constAccessor;
    auto res = urmaConnectionMap_.find(constAccessor, hostAddress);
    if (!res) {
        RETURN_STATUS(K_URMA_NEED_CONNECT, "No existing connection requires creation.");  // 无日志
    }
    ...
    if (!instanceId.empty()) {
        CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(..., K_URMA_NEED_CONNECT,
                                             "Urma connect has disconnected ...");  // 有日志（PRINT_ERROR）
        return Status::OK();
    }
    RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect unstable, need to reconnect!");  // 无日志
}
```

第 1297 行和第 1306 行只用了 `RETURN_STATUS`（不打日志），而第 1301-1303 行用了 `CHECK_FAIL_RETURN_STATUS_PRINT_ERROR`（有日志）。

### 修改方案

```diff
 Status UrmaManager::CheckUrmaConnectionStable(const std::string &hostAddress, const std::string &instanceId)
 {
     TbbUrmaConnectionMap::const_accessor constAccessor;
     auto res = urmaConnectionMap_.find(constAccessor, hostAddress);
     if (!res) {
-        RETURN_STATUS(K_URMA_NEED_CONNECT, "No existing connection requires creation.");
+        LOG(WARNING) << "[URMA_NEED_CONNECT] No existing connection for host: " << hostAddress
+                     << ", requires creation.";
+        RETURN_STATUS(K_URMA_NEED_CONNECT, "No existing connection requires creation.");
     }
     CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(constAccessor->second != nullptr, K_RUNTIME_ERROR, "Urma connection is null");
     if (!instanceId.empty()) {
         CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(constAccessor->second->GetUrmaJfrInfo().uniqueInstanceId == instanceId,
                                              K_URMA_NEED_CONNECT,
                                              "Urma connect has disconnected and needs to be reconnected!");
         return Status::OK();
     }
-    RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect unstable, need to reconnect!");
+    LOG(WARNING) << "[URMA_NEED_CONNECT] Connection unstable for host: " << hostAddress
+                 << ", instanceId mismatch or empty, need to reconnect.";
+    RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect unstable, need to reconnect!");
 }
```

---

## P4：`ServerEventHandleThreadMain` 忽略 `PollJfcWait` 返回

### 现状分析

**当前代码**（`urma_manager.cpp:596-619`）：

```cpp
Status UrmaManager::ServerEventHandleThreadMain()
{
    while (!serverStop_.load()) {
        ...
        Status rc = PollJfcWait(urmaResource_->GetJfc(), MAX_POLL_JFC_TRY_CNT, successCompletedReqs,
                                failedCompletedReqs, FLAGS_urma_poll_size);
        // rc 被忽略！
        if (successCompletedReqs.size()) { ... }
        if (failedCompletedReqs.size()) { ... }
        CheckAndNotify();
    }
    return Status::OK();
}
```

`PollJfcWait` 可能返回以下错误：
- `K_URMA_ERROR`：`ds_urma_wait_jfc` 失败 / `ds_urma_poll_jfc` 失败 / `ds_urma_rearm_jfc` 失败
- `K_TRY_AGAIN`：poll 轮询超过 `maxTryCount` 无事件

这些错误被完全忽略，意味着：
- `ds_urma_wait_jfc` 返回异常（如 -1）时，循环继续但没有记录异常频率
- 如果 `PollJfcWait` 在 `wait_jfc` 阶段失败，`failedCompletedReqs` 为空，对应的 waiter 只能等到超时（`Event::WaitFor` 超时），延迟增大但无错误上下文

### 修改方案

```diff
 Status UrmaManager::ServerEventHandleThreadMain()
 {
     while (!serverStop_.load()) {
         std::unordered_set<uint64_t> successCompletedReqs;
         std::unordered_map<uint64_t, int> failedCompletedReqs;
         Status rc = PollJfcWait(urmaResource_->GetJfc(), MAX_POLL_JFC_TRY_CNT, successCompletedReqs,
                                 failedCompletedReqs, FLAGS_urma_poll_size);
+        if (rc.IsError() && rc.GetCode() != K_TRY_AGAIN) {
+            LOG(ERROR) << "[URMA_POLL_ERROR] ServerEventHandleThreadMain PollJfcWait failed: " << rc.ToString();
+        }
 
         if (successCompletedReqs.size()) {
```

---

## P5：URMA 事件处理缺乏连接/操作上下文

### 现状分析

`HandleUrmaEvent`（`urma_manager.cpp:717-737`）当 CR.status 异常时只打印了 requestId 和 cqe status，没有打印：
- 对端 Worker 地址
- 关联的 JFS ID
- 操作类型（write / read）

### 修改方案

```diff
 Status UrmaManager::HandleUrmaEvent(uint64_t requestId, const std::shared_ptr<UrmaEvent> &event)
 {
     RETURN_OK_IF_TRUE(!event->IsFailed());
 
     const auto statusCode = event->GetStatusCode();
     const auto policy = GetUrmaErrorHandlePolicy(statusCode);
-    auto errMsg = FormatString("Polling failed with an error for requestId: %d, cqe status: %d", requestId, statusCode);
+    auto connection = event->GetConnection().lock();
+    auto jfs = event->GetJfs().lock();
+    std::string connInfo = connection ? connection->GetUrmaJfrInfo().ToString() : "expired";
+    uint32_t jfsId = jfs ? jfs->GetJfsId() : 0;
+    auto errMsg = FormatString("[URMA_CQE_ERROR] requestId: %d, cqe status: %d, connection: %s, jfsId: %u",
+                               requestId, statusCode, connInfo.c_str(), jfsId);
+    LOG(ERROR) << errMsg;
     if (policy == UrmaErrorHandlePolicy::RECREATE_JFS) {
-        LOG(WARNING) << "Recreate JFS for requestId: " << requestId << " due to error status code: " << statusCode;
-        auto connection = event->GetConnection().lock();
-        auto oldJfs = event->GetJfs().lock();
+        LOG(WARNING) << "[URMA_JFS_RECREATE] Recreate JFS for requestId: " << requestId
+                     << ", connection: " << connInfo << ", jfsId: " << jfsId
+                     << " due to error status code: " << statusCode;
         if (connection != nullptr) {
-            LOG_IF_ERROR(connection->ReCreateJfs(*urmaResource_, oldJfs),
-                         FormatString("Recreate JFS for requestId: %d failed", requestId));
+            LOG_IF_ERROR(connection->ReCreateJfs(*urmaResource_, jfs),
+                         FormatString("[URMA_JFS_RECREATE_FAILED] Recreate JFS for requestId: %d, "
+                                     "connection: %s failed", requestId, connInfo.c_str()));
         } else {
             LOG(WARNING) << "Event connection expired, cannot recreate JFS for requestId: " << requestId;
         }
```

---

## P6：1002 桶码子分类

已在 P2 中通过日志前缀方案统一解决。

---

## P7：JFS 重建缺乏 metrics 和详细日志

### 修改方案

在 `HandleUrmaEvent` 中增加计数器（待 metrics 基础设施就绪后接入）：

```diff
     if (policy == UrmaErrorHandlePolicy::RECREATE_JFS) {
+        // TODO(metrics): 接入 metrics 后改为 counter 递增
+        static std::atomic<uint64_t> jfsRecreateCount{0};
+        jfsRecreateCount.fetch_add(1);
+        VLOG(0) << "[URMA_JFS_RECREATE_METRIC] Total JFS recreate count: " << jfsRecreateCount.load();
```

---

## P8：性能 Metrics 缺口补充

### 用户已梳理的 Metrics 表

| 组件 | 归属流程 | Metrics | 打点 |
|------|---------|---------|------|
| SDK | ① 读取请求-共享内存 | P99时延 | client_rpc_get_latency |
| SDK | ① 读取请求-UB | P99时延 | client_get_urma_write_latency |
| SDK | ① 读取请求-共享内存 | P99时延 | client_get_request_total |
| SDK | ① 读取请求-UB | 数据量 | client_get_urma_write_total_bytes |
| SDK | ① 读取请求-TCP | 数据量 | client_get_tcp_write_total_bytes |
| worker | ② 元数据查询-TCP | P99时延 | worker_rpc_query_meta_latency |
| worker | ③ 远端数据拉取请求-TCP | P99时延 | worker_rpc_get_remote_latency |
| worker | ④ 远端数据传输-UB | P99时延 | worker_worker_urma_write_latency |
| worker | ④ 远端数据传输-TCP | P99时延 | worker_worker_tcp_write_latency |
| worker | ① 读取请求处理-UB | 数据量 | worker_to_client_urma_write_total_bytes |
| worker | ① 读取请求处理-TCP | 数据量 | worker_to_client_tcp_write_total_bytes |
| worker | ④ 远端数据传输-UB | 数据量 | worker_worker_urma_write_total_bytes |
| worker | ④ 远端数据传输-TCP | 数据量 | worker_worker_tcp_write_total_bytes |

### 建议补充的 Metrics

| 组件 | 归属流程 | Metrics | 建议打点名 | 理由 |
|------|---------|---------|-----------|------|
| SDK | Init-UB握手 | 成功/失败计数 | `client_urma_handshake_total` (label: result=success/fail) | 握手失败回退 TCP 是关键降级信号 |
| SDK | ① 读取请求 | UB fallback TCP 计数 | `client_get_ub_fallback_tcp_total` | FM-014 性能告警核心指标，对应 `Prepare UB Get request failed... fallback` 日志 |
| SDK | 写路径 | MSet/Publish P99时延 | `client_rpc_publish_latency` | 与读路径对称，写路径目前缺 P99 |
| SDK | 写路径-UB | 数据量 | `client_put_urma_write_total_bytes` | 与读路径对称 |
| worker | URMA CQ | wait/poll 失败计数 | `worker_urma_poll_error_total` | FM-011 核心指标，对应 `Failed to poll/wait jfc` |
| worker | URMA CQ | wait 耗时 | `worker_urma_wait_latency` | 已有 PerfKey::URMA_WAIT_TIME，需导出为 metrics |
| worker | URMA 连接 | 重连次数 | `worker_urma_reconnect_total` | FM-012 核心指标，`TryReconnectRemoteWorker` 触发频率 |
| worker | URMA JFS | JFS 重建次数 | `worker_urma_jfs_recreate_total` | FM-013 核心指标 |
| worker | 远端拉取 | 远端 Get 成功率 | `worker_remote_get_total` (label: result=success/fail) | 区分远端拉取成功/失败比 |
| worker | Init | Worker Register 耗时 | `worker_register_client_latency` | 部署期排障关键 |

---

## P9：URMA 关键操作缺乏 Trace 上下文

### 现状分析

当前 URMA 操作有 PerfPoint 但缺乏与请求级 TraceID 的关联：
- `ServerEventHandleThreadMain` 是独立后台线程，无 TraceGuard
- `UrmaWritePayload` / `PollJfcWait` 由业务线程调用，理论上继承 Trace，但 URMA 内部日志未打印 TraceID
- `HandleUrmaEvent` / `CheckCompletionRecordStatus` 在 event 线程中，无法获取原始请求的 TraceID

### 修改方案

**方案核心**：在 `UrmaEvent` 中携带调用方上下文信息（不需要完整的 Trace 传播，而是在 Event 创建时记录关键字段）。

**Step 1：`UrmaEvent` 增加上下文字段**

文件：`src/datasystem/common/rdma/urma_resource.h`

```diff
 class UrmaEvent : public Event {
 public:
     ...
+    void SetCallerContext(const std::string &remoteHost, const std::string &operationType) {
+        remoteHost_ = remoteHost;
+        operationType_ = operationType;
+    }
+    const std::string &GetRemoteHost() const { return remoteHost_; }
+    const std::string &GetOperationType() const { return operationType_; }
 private:
     ...
+    std::string remoteHost_;
+    std::string operationType_;
 };
```

**Step 2：`CreateEvent` 调用处设置上下文**

在 `UrmaWritePayload` 和 `UrmaReadPayload` 调用 `CreateEvent` 后，补充 `SetCallerContext`。

**Step 3：`HandleUrmaEvent` 和 `CheckCompletionRecordStatus` 中利用上下文打日志**

在错误日志中追加 `remoteHost` 和 `operationType`，便于跨 Worker 关联。

---

## 修改实施计划

### Phase 1：错误码与日志修正（P0-P1，建议本迭代完成）

| 序号 | 改动 | 文件 | 评估工作量 |
|------|------|------|-----------|
| 1.1 | 新增 `K_URMA_WAIT_TIMEOUT` | `status_code.def` | 小 |
| 1.2 | `Event::WaitFor` / `EventWaiter::WaitAny` 错误码修正 | `rdma_util.h` | 小 |
| 1.3 | `WaitToFinish` 错误码修正 | `urma_manager.cpp` | 小 |
| 1.4 | 外层重试集合适配新错误码 | `worker_oc_service_get_impl.cpp`, `worker_oc_service_batch_get_impl.cpp` | 中（需回归） |
| 1.5 | `CheckUrmaConnectionStable` 增加 WARNING 日志 | `urma_manager.cpp` | 小 |
| 1.6 | `ServerEventHandleThreadMain` 增加错误日志 | `urma_manager.cpp` | 小 |
| 1.7 | 1002 子分类日志前缀 | `zmq_msg_queue.h`, `zmq_stub_impl.h`, `zmq_stub_conn.cpp`, `unix_sock_fd.cpp`, `client_worker_common_api.cpp` | 中 |

### Phase 2：可观测增强（P2，建议下迭代完成）

| 序号 | 改动 | 文件 | 评估工作量 |
|------|------|------|-----------|
| 2.1 | `HandleUrmaEvent` 增加连接/JFS 上下文 | `urma_manager.cpp` | 小 |
| 2.2 | JFS 重建 metrics 预埋 | `urma_manager.cpp` | 小 |
| 2.3 | `UrmaEvent` 增加 caller 上下文 | `urma_resource.h`, 调用处 | 中 |
| 2.4 | 补充 Metrics 采集（见 P8 表） | 多文件 | 大（需与 metrics 基础设施协同） |

### 回归验证要点

1. **`K_URMA_WAIT_TIMEOUT` 回归**：
   - UT：模拟 URMA 事件超时，验证返回码为 `K_URMA_WAIT_TIMEOUT` 而非 `K_RPC_DEADLINE_EXCEEDED`
   - ST：注入 `UrmaManager.UrmaWaitError`，验证 worker 侧远端拉取能正确重试
   - 确认日志中 `[URMA_WAIT_TIMEOUT]` 可被 grep 到

2. **1002 子分类回归**：
   - 确认各类 1002 场景日志均携带正确前缀
   - 确认 `RetryOnError` 行为不受影响（错误码数值未变）

3. **URMA 日志增强回归**：
   - `CheckUrmaConnectionStable` 触发时 WARNING 日志可见
   - `ServerEventHandleThreadMain` 遇到 `K_URMA_ERROR` 时 ERROR 日志可见
   - `HandleUrmaEvent` 日志含连接信息

---

## 执行计划（供 Review）

本节给出按迭代落地的执行顺序、测试设计、无 URMA 环境验证方案和真实 URMA 环境补验方案。目标是先锁住**错误码语义**、再锁住**重试行为**、最后补齐**日志/metrics/trace**，避免一次性改太多导致回归面失控。

### 目标与范围

| 目标 | 本次覆盖 | 本次不覆盖 |
|------|----------|-----------|
| 错误码分层 | 区分 TCP/RPC 与 URMA wait timeout | 不重构现有所有 RPC 错误码体系 |
| 日志可观测 | 补齐 reconnect / poll error / 1002 子分类 | 不一次性重做所有历史日志格式 |
| 重试行为 | 让 URMA wait timeout 进入正确重试集合 | 不调整全局 `RetryOnError` 策略 |
| 性能观测 | 输出 metrics 补充清单与埋点位置 | 不在本轮完成全部 metrics 平台接入 |
| 验证策略 | UT + ST + 无 URMA 环境验证 + 真实 URMA 环境补验 | 不在无 URMA 环境下声称完成真实链路验证 |

### Phase 0：变更前基线确认

目标：先把当前行为留痕，避免改完后说不清“原来是什么样”。

1. 记录当前关键错误码和日志现状：
   - `Event::WaitFor` / `EventWaiter::WaitAny` 当前返回 `K_RPC_DEADLINE_EXCEEDED`
   - `CheckUrmaConnectionStable` 某些分支无日志
   - `ServerEventHandleThreadMain` 对 `PollJfcWait` 返回值静默丢弃
   - ZMQ `TRY_AGAIN` 在阻塞路径被改写为 `K_RPC_UNAVAILABLE`
2. 保存现有可复用的注入点与 ST 文件：
   - `UrmaManager.UrmaWaitError`
   - `UrmaManager.UrmaWriteError`
   - `UrmaManager.CheckCompletionRecordStatus`
   - `worker.remote_get_failed`
   - `worker.before_query_meta`
3. 对现有测试建立映射清单：
   - `tests/st/client/object_cache/urma_object_client_test.cpp`
   - `tests/st/client/kv_cache/kv_cache_client_test.cpp`
   - `tests/st/client/object_cache/object_client_with_tcp_test.cpp`

输出物：
- 一份当前行为基线说明
- 一份测试复用清单

### Phase 1：最小语义修复

目标：先修正最关键、最独立的问题，控制改动面。

#### 1.1 错误码修复

改动项：
- 新增 `K_URMA_WAIT_TIMEOUT`
- 修改 `Event::WaitFor`
- 修改 `EventWaiter::WaitAny`
- 修改 `UrmaManager::WaitToFinish`

预期结果：
- URMA 等待超时不再伪装成 RPC 超时
- 后续运维分桶可直接区分 TCP/URMA

#### 1.2 重试集合修复

改动项：
- `worker_oc_service_get_impl.cpp`
- `worker_oc_service_batch_get_impl.cpp`

预期结果：
- `K_URMA_WAIT_TIMEOUT` 进入远端读路径的可重试集合
- 保持“预算足够则可重试成功，预算不足则正确失败”的行为

#### 1.3 关键日志补齐

改动项：
- `CheckUrmaConnectionStable` 增加 `[URMA_NEED_CONNECT]`
- `ServerEventHandleThreadMain` 增加 `[URMA_POLL_ERROR]`

预期结果：
- reconnect 触发时刻可被直接检索
- `PollJfcWait` 的异常不再静默丢失

完成门槛：
- 代码编译通过
- 现有无关 ST 不回归
- 新增 UT 全绿

### Phase 2：1002 子分类与日志兼容

目标：不改 1002 数值，只提升可观测性。

改动项：
- `zmq_msg_queue.h`
- `zmq_stub_impl.h`
- `zmq_stub_conn.cpp`
- `unix_sock_fd.cpp`
- `client_worker_common_api.cpp`

新增日志前缀：
- `[RPC_RECV_TIMEOUT]`
- `[TCP_CONN_RESET]`
- `[TCP_CONN_TIMEOUT]`
- `[TCP_NETWORK_UNREACHABLE]`
- `[TCP_SERVICE_UNAVAILABLE]`
- `[SHM_FD_TRANSFER_FAILED]`

兼容要求：
- 保留旧关键词主体，例如 `Connect reset`、`Remote service is not available`
- 仅在消息前加前缀，不改已有错误码

完成门槛：
- 新旧 grep 都能命中
- 1002 相关回归测试通过

### Phase 3：URMA 上下文与 metrics 预埋

目标：给后续 Trace / metrics 铺路，但不让本轮过重。

改动项：
- `HandleUrmaEvent` 增加 connection/JFS 上下文
- `UrmaEvent` 记录 `remoteHost` / `operationType`
- JFS recreate 计数预埋
- 按 P8 表补充 metrics 埋点位置

建议本轮只完成：
- 日志上下文增强
- metrics 埋点位置设计与接口预留

建议下轮完成：
- metrics 真实上报
- Trace 体系接入

#### Phase 3 评审清单（按文件-函数-改动点）

1. `src/datasystem/common/rdma/urma_resource.h`
   - `class UrmaEvent`：新增只读上下文字段（建议最小集合）
     - `std::string remoteHost`
     - `std::string operationType`（建议值域：`READ`/`WRITE`）
   - 约束：构造后不再修改，避免并发路径读写冲突。

2. `src/datasystem/common/rdma/urma_manager.cpp`
   - `CreateEvent(...)`：创建 `UrmaEvent` 时写入 `remoteHost/operationType`。
   - `WaitToFinish(...)`：按当前请求语义向 `CreateEvent` 传递 operationType（读路径标记 `READ`，写路径标记 `WRITE`）。
   - `HandleUrmaEvent(...)`：
     - 在 `RECREATE_JFS` 分支日志中补充：`requestId`、`remoteHost`、`operationType`、`oldJfsId/newJfsId`（可取到时）。
     - 新增 JFS recreate 计数预埋（本轮允许仅日志或 TODO 接口，不强依赖完整 metrics 框架）。
   - `ServerEventHandleThreadMain(...)`：在 `URMA_POLL_ERROR` 日志追加最小上下文（建议包含 `requestId`/`wc status` 聚合信息，避免仅有 rc 文本）。

3. `src/datasystem/common/rdma/urma_resource.cpp`
   - `UrmaConnection::RecreateJfs(...)`：
     - 保留现有并发保护语义（`jfsMutex_` + `MarkInvalid` 逻辑）不变。
     - 在“跳过重建/已失效/成功重建”分支补充结构化日志字段，便于后续聚合统计。

4. `src/datasystem/client/client_worker_common_api.cpp`
   - `ConnectUrma(...)`/握手路径：补一个轻量计数埋点位置（例如“URMA 建连尝试次数”预留接口）。
   - 目标：与 worker 侧指标拼接时可还原“建连失败是否集中在客户端入口”。

5. `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp`
   - `PullRemoteData*`/`QueryMeta*` 相关路径：
     - 明确标注 TCP 与 URMA 分支的埋点挂载点（仅“位置确定 + 接口预留”）。
   - 对齐原则：同一语义阶段保持“TCP/URMA 成对”命名，避免后续报表难对比。

#### Phase 3 出口标准（供评审对齐）

- 代码层：`UrmaEvent` 上下文可在关键错误日志中被打印出来（至少 `remoteHost + operationType + requestId`）。
- 可观测层：JFS recreate 具备可计数入口（本轮可先日志统计，或预留 metrics 接口）。
- 兼容层：不改现有错误码，不改变既有重试行为，不引入新失败路径。
- 验证层：新增/调整 UT 至少覆盖“上下文字段传递不丢失”；ST 在 URMA 环境验证日志可检索性。

#### Phase 3 性能开销控制（低开销实现约束）

1. `UrmaEvent` 字段类型约束
   - `operationType` 使用 `enum class`（禁止用 `std::string`）。
   - `remoteHost` 优先使用稳定短标识（如 `hostId`/`endpoint hash`）；如必须存原始字符串，要求复用连接对象已有值，避免每请求重复深拷贝。

2. 日志路径约束（故障风暴保护）
   - `HandleUrmaEvent(...)`、`ServerEventHandleThreadMain(...)`、`RecreateJfs(...)` 新增日志必须带节流（如 `LOG_EVERY_N` 或同等级限频机制）。
   - 仅保留最小关键字段：`requestId`、`hostId(remoteHost)`、`operationType`、`jfsId/statusCode`，禁止在热路径拼接大字符串。

3. 计数器实现约束
   - JFS recreate 计数预埋采用轻量原子或线程本地聚合方案；禁止引入全局大锁。
   - 计数更新不得扩大 `jfsMutex_` 临界区时长，避免影响并发写路径。

4. 指标接入边界（本轮）
   - 本轮仅做“埋点位置 + 接口预留”，不接入高频同步上报。
   - 若需临时观测，优先使用低频聚合日志替代实时逐请求上报。

5. 性能验收基线（本轮建议）
   - 非故障场景：不引入可见吞吐下降（建议门槛 `< 1%`）。
   - 故障场景：日志量受控，不出现日志反压导致的连锁超时放大。
   - 内存增量：按峰值并发评估 `UrmaEvent` 新字段，确认无异常增长。

---

## 测试用例验证计划

### A. 单元测试（UT）

目标：验证“新错误码”和“局部语义”。

#### UT-1 `Event::WaitFor` 超时返回码

覆盖点：
- 超时返回 `K_URMA_WAIT_TIMEOUT`
- 非超时返回 `Status::OK()`

建议断言：
- `WaitFor(0ms)` 或极短超时返回新码
- `NotifyAll()` 后返回 OK

#### UT-2 `EventWaiter::WaitAny` 超时返回码

覆盖点：
- 超时返回 `K_URMA_WAIT_TIMEOUT`
- 有事件时返回 OK

#### UT-3 `CheckUrmaConnectionStable` 返回码

覆盖点：
- 无连接 -> `K_URMA_NEED_CONNECT`
- instanceId 不一致 -> `K_URMA_NEED_CONNECT`
- 正常 -> OK

说明：
- 若当前 UT 框架不方便断日志，日志部分放到 ST 验证

### B. 集成/系统测试（ST）

目标：验证端到端行为、重试语义和日志可见性。

#### ST-1 URMA wait timeout 码值回归

复用注入点：
- `UrmaManager.UrmaWaitError`

建议场景：
1. 单次 remote get
2. batch get

断言：
- 最终失败时返回 `K_URMA_WAIT_TIMEOUT`，而不是 `K_RPC_DEADLINE_EXCEEDED`
- 日志包含 `[URMA_WAIT_TIMEOUT]`

#### ST-2 URMA wait timeout 重试成功

复用注入点：
- `UrmaManager.UrmaWaitError`

建议场景：
- 只注入前 1 次 wait error，后续成功

断言：
- 外层 `RetryOnError` 能继续重试
- 最终请求成功

#### ST-3 URMA need reconnect

建议方式：
- 若有现成注入点，直接注入 `K_URMA_NEED_CONNECT`
- 若无，补一个轻量 inject point，仅用于测试

断言：
- `CheckUrmaConnectionStable` 触发时有 `[URMA_NEED_CONNECT]`
- `TryReconnectRemoteWorker` 被触发
- reconnect 成功后请求最终成功

#### ST-4 PollJfcWait 非 OK 不再静默

建议方式：
- 通过 `UrmaManager.CheckCompletionRecordStatus` 或新增注入点制造 `PollJfcWait` 异常

断言：
- worker 日志出现 `[URMA_POLL_ERROR]`
- 不再出现“只有请求超时、没有中间错误锚点”的情况

#### ST-5 1002 子分类日志

复用现有注入点：
- `ZmqSockConnHelper.StubConnect`
- `ZmqBaseStubConn.WaitForConnect`
- `ClientWorkerCommonApi.GetClientFd.preReceive`
- `worker.before_GetClientFd`

断言：
- 各场景出现正确日志前缀
- 错误码仍是 `K_RPC_UNAVAILABLE`

#### ST-6 回归护栏

目标：
- 证明这次修复没有破坏主流程

覆盖：
- TCP 模式 `Get/MGet/MSet`
- 现有 `UrmaFallbackTest`
- 现有 `ObjectClientWithTCPTest`

---

## 非 URMA 环境验证方案

当前没有真实 URMA 环境时，验证目标应调整为：**验证代码语义正确性** 和 **验证可观测行为正确性**，而不是验证真实硬件链路。

### 可验证的内容

| 类别 | 可验证 | 方法 |
|------|--------|------|
| 错误码语义 | 是 | UT + 注入式 ST |
| 重试行为 | 是 | 注入 `UrmaWaitError` / need reconnect |
| 日志可见性 | 是 | grep 日志前缀 |
| 1002 子分类 | 是 | TCP/UDS 注入 |
| metrics 存在性设计 | 是 | 埋点位置设计 + 后续 mock 校验 |
| 真实 URMA 建链/重连/JFC 行为 | 否 | 需真实 URMA 环境 |
| 真实 URMA 时延/吞吐指标 | 否 | 需真实 URMA 环境 |

### 非 URMA 环境的验证执行顺序

1. 跑 UT：
   - `Event::WaitFor`
   - `EventWaiter::WaitAny`
   - `CheckUrmaConnectionStable`
2. 跑注入式 ST：
   - `UrmaManager.UrmaWaitError`
   - `UrmaManager.CheckCompletionRecordStatus`
3. 跑纯 TCP/ST：
   - `object_client_with_tcp_test`
   - `kv_cache_client_test` 中相关 TCP case
4. 日志验收：
   - grep `[URMA_WAIT_TIMEOUT]`
   - grep `[URMA_NEED_CONNECT]`
   - grep `[URMA_POLL_ERROR]`
   - grep 各类 1002 子分类前缀

### 非 URMA 环境下的通过标准

1. 新增 UT 全绿
2. 注入式 ST 全绿
3. 纯 TCP/ST 不回归
4. 关键日志前缀都能 grep 到
5. 没有新增把 URMA 问题再映射回 `K_RPC_DEADLINE_EXCEEDED` 的路径

---

## 真实 URMA 环境补验计划

这部分是**上线前补验**，不能用无 URMA 环境替代。

### 最小补验用例

1. **单 key remote get**
   - 覆盖真实 `UrmaWritePayload` + `WaitToFinish`
   - 验证正常路径无回归

2. **batch get**
   - 覆盖 `PollJfcWait`
   - 验证 batch 场景下无异常放大

3. **worker 重启 / reconnect**
   - 触发 `K_URMA_NEED_CONNECT`
   - 验证 reconnect 行为与日志

4. **长时间压测**
   - 观察 wait timeout、poll error、JFS recreate
   - 验证 metrics 统计是否合理

### 真实 URMA 环境验收项

| 验收项 | 通过标准 |
|--------|----------|
| 正常读写 | 成功率不低于改动前基线 |
| URMA wait timeout | 只在真实异常场景出现，且错误码为 `K_URMA_WAIT_TIMEOUT` |
| reconnect | 日志和行为一致，成功时请求可恢复 |
| 1002 分类 | 仅 TCP/RPC 场景出现，不混入 URMA wait timeout |
| metrics | 至少能看到关键埋点有值或有样本 |

---

## 执行排期建议

### 第 1 天

1. 完成 Phase 1 代码修改
2. 补齐最小 UT
3. 本地编译 + 跑相关 UT

### 第 2 天

1. 完成注入式 ST
2. 完成 TCP 1002 子分类改造
3. 跑相关 ST 和 TCP 回归

### 第 3 天

1. 补齐日志验收脚本或手工 grep 清单
2. 输出 metrics 埋点设计清单
3. 形成提交说明和变更说明

### 拿到 URMA 环境后

1. 跑 4 组最小补验用例
2. 对照日志和 metrics 做验收
3. 若通过，再进入灰度/上线

---

## Review 关注点

本计划建议 review 时重点看以下问题：

1. 是否接受 `K_URMA_WAIT_TIMEOUT` 作为新错误码，而不是复用 `K_URMA_ERROR`
2. 是否接受 1002 仅做“日志子分类”，本轮不改错误码数值
3. `K_URMA_WAIT_TIMEOUT` 是否应进入远端读路径 retry 集合
4. `CheckUrmaConnectionStable` 是否只打 `WARNING`，还是部分场景要提到 `ERROR`
5. 无 URMA 环境下，是否接受“语义验证通过 + 真实链路待补验”的结论边界
6. metrics 本轮是只做清单和接口预埋，还是要一起接入真实上报

---

## 当前执行状态（2026-04-15）

### 已完成

1. Phase 1 核心代码修改已落地（错误码、日志、重试集合相关改造）。
2. 目标 UT 已验证通过：
   - `StatusTest.EventWaitForTimeoutReturnsUrmaWaitTimeout`
   - `StatusTest.EventWaitForSucceedsAfterNotify`
   - `StatusTest.EventWaitAnyTimeoutReturnsUrmaWaitTimeout`
   - `StatusTest.EventWaitAnySucceedsAfterNotify`
3. `ds_st_object_cache` 目标已在非 URMA 配置下完成构建。
4. Phase 2（1002 子分类）代码改造已落地，已补充以下前缀：
   - `[RPC_RECV_TIMEOUT]`
   - `[RPC_SERVICE_UNAVAILABLE]`
   - `[TCP_NETWORK_UNREACHABLE]`
   - `[SOCK_CONN_WAIT_TIMEOUT]`
   - `[REMOTE_SERVICE_WAIT_TIMEOUT]`
   - `[TCP_CONNECT_RESET]`
   - `[TCP_CONNECT_FAILED]`
   - `[UDS_CONNECT_FAILED]`
   - `[SHM_FD_TRANSFER_FAILED]`
5. 已新增并补齐最小 UT 用例 `UnixSockFdStatusTest`（用于覆盖 1002 子分类中的 TCP reset 映射语义）：
   - `ConnectResetMapsToRpcUnavailableWithPrefix`
   - `EagainMapsToTryAgain`
   - `EpipeMapsToRpcUnavailableWithPrefix`
6. Phase 2 定向验证已完成：
   - `ctest -R "UnixSockFdStatusTest"` 通过（3/3 PASS）。
7. Phase 3（第一批）已落地：
   - `UrmaEvent` 增加只读上下文：`remoteAddress`、`remoteInstanceId`、`operationType(enum)`。
   - 故障日志按规则改造为“故障路径打印 + 限频”（`URMA_POLL_ERROR`、`URMA_RECREATE_JFS*`、`URMA_NEED_CONNECT`）。
   - `remoteAddress` 统一记录为 `host:port`（不再复用 `client_id` 作为地址字段，避免排障歧义）。
8. 本地编译验证：
   - `cmake --build ... --target common_rdma` 通过。
9. Phase 3（worker 侧关联补充）已落地：
   - 在 `TryReconnectRemoteWorker` 与 `CheckConnectionStable` 的 `K_URMA_NEED_CONNECT` 故障日志中补充 `remoteWorkerId`（由 `remoteAddress -> workerId` 映射得到）。
   - 保持“仅故障路径打印 + 限频”原则，不修改 RPC/URMA 协议字段。
10. Phase 4（日志验收脚本化）已落地第一版：
   - 新增脚本 `scripts/testing/verify/validate_urma_tcp_observability_logs.sh`；
   - 新增统一入口命令 `./ops test.urma_tcp_logs`；
   - 已将脚本调用方式补入 `kv-client-URMA环境验证执行清单.md`。

### 待 URMA 环境补验

1. `UrmaDisableFallbackTest.TestUrmaRemoteGetWaitTimeoutReturnsUrmaWaitTimeout`
2. `K_URMA_NEED_CONNECT` 触发路径日志可检索性（含 host/重连触发时机）
3. `PollJfcWait` 非 `K_TRY_AGAIN` 错误日志可检索性
4. URMA 与 TCP 定界一致性（错误码、日志前缀、排障路径）

### 当前阻塞与边界说明

- 当前环境 `BUILD_WITH_URMA=off`，URMA 专项 ST 在该配置下不会进入可执行用例集合（可能出现 `0 tests`）。
- 因此当前结论边界为：**语义改造已通过 UT 与非 URMA 构建验证，真实 URMA 链路行为需专用环境补验**。
- 本地 `p2-verify`（`UnixSockFdStatusTest.*`）已完成并通过；真实 URMA 链路验证仍需 URMA 专用环境补齐。

---

## 协作交接说明（给 URMA 环境同事）

1. 先按 `kv-client-URMA环境验证执行清单.md` 完成 `BUILD_WITH_URMA=on` 的独立构建。
2. 严格按“UT -> ST -> 日志验收”的顺序执行，不建议跳步。
3. 输出结果时至少回填：
   - 构建参数（确认 `BUILD_WITH_URMA=on`）
   - 目标用例 PASS/FAIL
   - 关键日志片段（`URMA_NEED_CONNECT`、`URMA_POLL_ERROR`、`URMA_WAIT_TIMEOUT`）
   - 1002 子分类日志片段（至少包含 3 类前缀）
4. 若失败，附三项最小信息：
   - 失败命令
   - 首个报错栈/日志
   - 是否可稳定复现（次数与条件）

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-15 | 初版：9 个问题分析 + 代码修改方案 + 实施计划 |
| 2026-04-15 | 增补执行计划：测试用例设计、非 URMA 环境验证、真实 URMA 环境补验 |
| 2026-04-15 | 增补当前执行状态、阻塞边界与 URMA 环境协作交接说明 |
| 2026-04-15 | 补充 Phase 2（1002 子分类）落地状态、前缀清单与验证阻塞说明 |
| 2026-04-15 | 更新进展：Phase 2 定向用例已通过（UnixSockFdStatusTest 3/3） |
| 2026-04-15 | 增补 Phase 3 评审清单（按文件-函数-改动点）与出口标准 |
| 2026-04-15 | 增补 Phase 3 性能开销控制约束（字段/日志/计数器/验收基线） |
| 2026-04-15 | 更新 Phase 3 第一批代码进展：故障限频日志 + URMA 事件上下文 + remoteAddress 语义修正 |
| 2026-04-15 | 更新 Phase 3 worker 侧关联补充：URMA_NEED_CONNECT 日志增加 remoteWorkerId |
| 2026-04-15 | 更新 Phase 4 进展：新增 URMA/TCP 日志自动验收脚本与 ops 入口 |
