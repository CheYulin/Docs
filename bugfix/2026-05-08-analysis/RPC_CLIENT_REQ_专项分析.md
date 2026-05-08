# ZMQ RPC Client 请求分析 (client_req_framework)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能正常 |
| **影响组件** | RPC Client -> RPC Server |
| **Trace ID** | metrics_client_req_framework_us_min_14_max_49 |

---

## 一、指标定义

### client_req_framework

**计算公式** (zmq_constants.h:174):
```cpp
uint64_t clientReqFrameworkNs = (clientSendTs > clientStartTs)
                                ? (clientSendTs - clientStartTs) : 0U;
```

**含义**: 从 RPC Client 开始处理请求到发送请求的时间。

### 时序位置

```
Client Side                          Server Side
    |                                     |
    |------ clientStartTs ----->|         |  <-- 开始
    |                           |         |
    |      [业务处理]            |         |
    |                           |         |
    |<----- clientSendTs --------| serverRecvTs  <-- 结束
```

---

## 二、Trace 0c3d819d 分析

### 2.1 日志

```
14:28:55.409808 | Remote get request | src=192.168.102.88:31402, dst=192.168.42.114:31402
14:28:55.409831 | Start to create stub | destAddr: 192.168.42.114:31402, type: 0
14:28:55.493757 | ZMQ_RPC_FRAMEWORK_SLOW | client_req_framework_us=49
```

### 2.2 Framework 数据

```
framework_us=82658
  client_req_framework_us=49        // ✅ 正常
  remote_processing_us=82639
  client_rsp_framework_us=12
```

### 2.3 代码确认

**文件**: `worker_oc_service_get_impl.cpp:117-131`

```cpp
Status WorkerOcServiceGetImpl::Get(
    std::shared_ptr<ServerUnaryWriterReader<GetRspPb, GetReqPb>> &serverApi)
{
    PerfPoint point(PerfKey::WORKER_GET_OBJECT);
    Timer timer;
    auto request = std::make_shared<GetRequest>(AccessRecorderKey::DS_POSIX_GET);
    INJECT_POINT("WorkerOCServiceImpl.Get.Retry", ...);

    GetReqPb req;
    // clientStartTs 记录点 (进入函数)
    // clientSendTs 记录点 (serverApi->Read 完成后)
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "serverApi read request failed");
    auto clientId = ClientKey::Intern(req.client_id());
    // ...
    LOG(INFO) << FormatString("[Get] Receive, clientId: %s, serverApiReadCost: %.3fms, ...",
                              clientId, timer.ElapsedMilliSecond());
}
```

**业务逻辑**:
1. 解析 GetReqPb 请求
2. 验证客户端身份
3. 构建 GetRequest 对象
4. 初始化请求上下文

---

## 三、结论

| 项目 | 结果 |
|------|------|
| 延迟 | 49us |
| 正常范围 | < 100us |
| 状态 | ✅ 正常 |

**根因**: client_req_framework 表现正常，不是瓶颈。

---

## 附录 A：全量日志

```
// ========== Trace 0c3d819d ==========

14:28:55.409808 | I | worker_oc_service_get_impl.cpp:1161 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Remote get request:[be68a78d-edde-4601-85a1-9840cefce853] object:[_urma_192_168_42_114:31402], offset[0] size[1], src=192.168.102.88:31402, dst=192.168.42.114:31402

14:28:55.409831 | I | rpc_stub_cache_mgr.cpp:191 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Start to create stub, destAddr: 192.168.42.114:31402, type: 0

14:28:55.493757 | I | zmq_constants.h:204 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=0c3d819d-c27b-4763-903e-82188ffde287 framework_us=82658 e2e_us=82701 client_req_framework_us=49 remote_processing_us=82639 client_rsp_framework_us=12 server_req_queue_us=65 server_exec_us=42 server_rsp_queue_us=21 network_residual_us=82509
```

---

## 附录 B：相关代码

**文件**: `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp`
**位置**: 第 117-131 行

```cpp
Status WorkerOcServiceGetImpl::Get(
    std::shared_ptr<ServerUnaryWriterReader<GetRspPb, GetReqPb>> &serverApi)
{
    PerfPoint point(PerfKey::WORKER_GET_OBJECT);
    workerOperationTimeCost.Clear();
    Timer timer;
    auto request = std::make_shared<GetRequest>(AccessRecorderKey::DS_POSIX_GET);
    INJECT_POINT("WorkerOCServiceImpl.Get.Retry",
                 [&serverApi]() { return serverApi->SendStatus(Status(K_TRY_AGAIN, "test get retry")); });
    GetReqPb req;
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "serverApi read request failed");
    auto clientId = ClientKey::Intern(req.client_id());
    auto inflightGauge = metrics::GetGauge(...);
    LOG(INFO) << FormatString("[Get] Receive, clientId: %s, serverApiReadCost: %.3fms, inflightRemoteGet: %d",
                              clientId, timer.ElapsedMilliSecond(), inflightGauge.Get());
    std::string tenantId;
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(worker::Authenticate(akSkManager_, req, tenantId), "Authenticate failed.");
    // ...
}
```
