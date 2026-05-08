# ZMQ RPC Client 响应等待分析 (client_rsp_framework)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能正常 |
| **影响组件** | RPC Client 响应接收 |
| **Trace ID** | metrics_client_rsp_framework |
| **正常 Trace** | 0c3d819d (12us) |

---

## 一、指标定义

### client_rsp_framework

**计算公式** (zmq_constants.h:175):
```cpp
uint64_t clientRspFrameworkNs = (clientEndTs > clientRecvTs)
                               ? (clientEndTs - clientRecvTs) : 0U;
```

**含义**: 从 RPC Client 收到响应到处理完成的时间。

### 时序位置

```
Client Side
    |
    |<---- clientRecvTs  收到响应
    |         |
    |         | [client_rsp_framework] <-- client_rsp_framework_us
    |         |
    |<---- clientEndTs  处理完成
```

---

## 二、Trace 0c3d819d 分析

### 2.1 日志

```
// Worker1 侧
14:28:55.409808 | Remote get request
14:28:55.503526 | Remote get success | elapsed 92.531 ms
14:28:55.493757 | ZMQ_RPC_FRAMEWORK_SLOW | client_rsp_framework_us=12
```

### 2.2 Framework 数据

```
framework_us=82658
  client_req_framework_us=49
  remote_processing_us=82639
  client_rsp_framework_us=12        // ✅ 正常
```

### 2.3 分析

```
client_rsp = 12us
remote_processing = 82639us

client_rsp / remote_processing = 0.01%
```

**结论**: client_rsp_framework 占比极小，说明响应处理很快。

---

## 三、代码分析

### 3.1 Worker1 收到响应

**文件**: `worker_oc_service_get_impl.cpp:165-200`

```cpp
// ThreadPool 中执行
threadPool_->Execute([=]() mutable {
    TraceGuard traceGuard = Trace::Instance().SetTraceContext(traceContext);
    workerOperationTimeCost = cost;

    const std::chrono::steady_clock::time_point poolThreadStart = std::chrono::steady_clock::now();
    {
        const uint64_t qUs = static_cast<uint64_t>(...);
        metrics::GetHistogram(...).Observe(qUs);
    }

    auto elapsed = static_cast<int64_t>(timer.ElapsedMilliSecond());
    LOG(INFO) << FormatString("[Get] Receive, clientId: %s, objects: %s, "
                              "threadPool: %s, elapsed: %.3fms, remainingTime: %.3fms",
                              clientId, VectorToString(request->GetRawObjectKeys()),
                              threadPool_->GetStatistics(), ...);

    if (elapsed >= timeout) {
        // 超时处理
    } else {
        reqTimeoutDuration.Init(timeout - elapsed);
        auto newSubTimeout = std::max<int64_t>(subTimeout - elapsed, 0);
        const std::chrono::steady_clock::time_point processStart = std::chrono::steady_clock::now();

        // 处理请求
        LOG_IF_ERROR(ProcessGetObjectRequest(newSubTimeout, request), "Process Get failed");

        // 记录执行时间
        {
            const uint64_t execUs = static_cast<uint64_t>(...);
            metrics::GetHistogram(...).Observe(execUs);
        }

        workerOperationTimeCost.Append("ProcessGetObjectRequest", ...);

        LOG(INFO) << FormatString(
            "[Get] Done, clientId: %s, objects: %zu, transferPath: %s, totalCost: %s",
            clientId, request->GetRawObjectKeys().size(),
            IsUrmaEnabled() ? "UB" : (IsUcpEnabled() ? "RDMA" : "TCP"),
            workerOperationTimeCost.GetInfo());
    }
});
```

---

## 四、结论

| 项目 | 结果 |
|------|------|
| client_rsp_framework | 12us |
| 正常范围 | < 100us |
| 状态 | ✅ 正常 |

**结论**: client_rsp_framework 表现正常，不是瓶颈。

---

## 附录 A：全量日志

```
// ========== Trace 0c3d819d ==========

// Worker1 (192.168.102.88) 侧

14:28:55.409808 | I | worker_oc_service_get_impl.cpp:1161 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Remote get request:[be68a78d-edde-4601-85a1-9840cefce853] object:[_urma_192_168_42_114:31402], offset[0] size[1], src=192.168.102.88:31402, dst=192.168.42.114:31402

14:28:55.409831 | I | rpc_stub_cache_mgr.cpp:191 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Start to create stub, destAddr: 192.168.42.114:31402, type: 0

14:28:55.493757 | I | zmq_constants.h:204 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=0c3d819d-c27b-4763-903e-82188ffde287 framework_us=82658 e2e_us=82701 client_req_framework_us=49 remote_processing_us=82639 client_rsp_framework_us=12 server_req_queue_us=65 server_exec_us=42 server_rsp_queue_us=21 network_residual_us=82509

14:28:55.503526 | I | worker_oc_service_get_impl.cpp:1256 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Remote get success, elapsed 92.531 ms
```

---

## 附录 B：相关代码

**文件**: `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp`
**位置**: 第 150-200 行

```cpp
if (serverApi->EnableMsgQ()) {
    const std::chrono::steady_clock::time_point submitToPool = std::chrono::steady_clock::now();
    auto traceContext = Trace::Instance().GetContext();
    auto cost = workerOperationTimeCost;

    threadPool_->Execute([=]() mutable {
        TraceGuard traceGuard = Trace::Instance().SetTraceContext(traceContext);
        workerOperationTimeCost = cost;
        const std::chrono::steady_clock::time_point poolThreadStart = std::chrono::steady_clock::now();

        // 记录 queue 延迟
        {
            const uint64_t qUs = static_cast<uint64_t>(
                std::chrono::duration_cast<std::chrono::microseconds>(poolThreadStart - submitToPool).count());
            metrics::GetHistogram(static_cast<uint16_t>(metrics::KvMetricId::WORKER_GET_THREADPOOL_QUEUE_LATENCY))
                .Observe(qUs);
        }

        auto elapsed = static_cast<int64_t>(timer.ElapsedMilliSecond());
        LOG(INFO) << FormatString("[Get] Receive, clientId: %s, objects: %s, "
                                  "threadPool: %s, elapsed: %.3fms, remainingTime: %.3fms",
                                  clientId, VectorToString(request->GetRawObjectKeys()),
                                  threadPool_->GetStatistics(),
                                  static_cast<double>(elapsed), static_cast<double>(timeout));

        if (elapsed >= timeout) {
            LOG(ERROR) << "RPC timeout...";
            LOG_IF_ERROR(serverApi->SendStatus(Status(K_RUNTIME_ERROR, "Rpc timeout")), "Send status failed");
        } else {
            reqTimeoutDuration.Init(timeout - elapsed);
            auto newSubTimeout = std::max<int64_t>(subTimeout - elapsed, 0);
            const std::chrono::steady_clock::time_point processStart = std::chrono::steady_clock::now();
            LOG_IF_ERROR(ProcessGetObjectRequest(newSubTimeout, request), "Process Get failed");

            // 记录执行延迟
            {
                const uint64_t execUs = static_cast<uint64_t>(
                    std::chrono::duration_cast<std::chrono::microseconds>(
                        std::chrono::steady_clock::now() - processStart).count());
                metrics::GetHistogram(static_cast<uint16_t>(metrics::KvMetricId::WORKER_GET_THREADPOOL_EXEC_LATENCY))
                    .Observe(execUs);
            }

            workerOperationTimeCost.Append("ProcessGetObjectRequest",
                                          static_cast<int64_t>(timer.ElapsedMilliSecond()));
            LOG(INFO) << FormatString(
                "[Get] Done, clientId: %s, objects: %zu, transferPath: %s, totalCost: %s",
                clientId, request->GetRawObjectKeys().size(),
                IsUrmaEnabled() ? "UB" : (IsUcpEnabled() ? "RDMA" : "TCP"),
                workerOperationTimeCost.GetInfo());
        }
    });
}
```
