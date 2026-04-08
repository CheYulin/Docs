# Client↔Worker、Worker↔Worker：TCP / UB（URMA）建链与失败处理 — 代码证据与结论

本文从**当前实现**出发，回答两件事：

1. **已有**哪些与「建链失败」相关的处理（重试、降级、回退）。
2. **缺少**哪些可称为「设计级机制」的能力（显式状态、统一策略、可观测与文档化流程）。

范围：`src/datasystem/client` 与 `src/datasystem/worker` 中与 **RPC 建连、SHM/UDS 辅助通道、URMA/UB 握手、Worker↔Worker 拉数** 相关的路径；不含纯 brpc/ZMQ 内部重连细节的全量展开。

---

## 1. Client ↔ Worker

### 1.1 主路径：`Connect` = RpcChannel +（可选）SHM/UDS + `RegisterClient`

远程客户端在 `ClientWorkerRemoteCommonApi::Connect` 中：

- 创建 `RpcChannel` / `WorkerService_Stub`（**业务 RPC 走 TCP/brpc 通道**，与 SHM 辅助通道分离）。
- 调用 `CreateConnectionForTransferShmFd`：先 `GetSocketPath`（带重试），再尝试 UDS/TCP 辅助握手；**失败时记录日志并回退到纯 TCP 语义**（不建 SHM 通道）。
- 若配置要求 **必须 UDS**（心跳类型或重连且曾启用 SHM）而 SHM 通道建失败，则 **直接返回 `K_RPC_UNAVAILABLE`**，不会静默继续。

证据：

```287:323:src/datasystem/client/client_worker_common_api.cpp
Status ClientWorkerRemoteCommonApi::Connect(RegisterClientReqPb &req, int32_t timeoutMs, bool reconnection)
{
    auto channel = std::make_shared<RpcChannel>(hostPort_, cred_);
    commonWorkerSession_ = std::make_unique<WorkerService_Stub>(channel);
    // ...
    RETURN_IF_NOT_OK(CreateConnectionForTransferShmFd(timeoutMs, isConnectSuccess, serverFd, socketFd, shmEnableType));
    if (mustUds && !isConnectSuccess) {
        return { StatusCode::K_RPC_UNAVAILABLE, "Can not create connection to worker for shm fd transfer." };
    }
    // ...
    RETURN_IF_NOT_OK(RegisterClient(req, timeoutMs));
    // ...
}
```

SHM 辅助建链失败时的 **显式回退**（日志 + 清空 shm 相关状态）：

```423:433:src/datasystem/client/client_worker_common_api.cpp
    if (rc.IsOk()) {
        isConnectSuccess = true;
        socketFd = sock.GetFd();
    } else {
        LOG(INFO) << "Failed connect to local worker via " << ShmEnableTypeName(shmEnableType)
                  << ", client and worker maybe not in the same node, falling back to TCP";
        shmEnableType = ShmEnableType::NONE;
        shmWorkerPort_ = 0;
    }
    return Status::OK();
}
```

`GetSocketPath` / `RegisterClient` 使用 `RetryOnError`，对 `K_TRY_AGAIN`、`K_RPC_DEADLINE_EXCEEDED`、`K_RPC_UNAVAILABLE` 等做**有限次重试**（**不是**独立的「建链状态机」文档，而是代码内嵌策略）。

证据（`RegisterClient` 片段）：

```574:593:src/datasystem/client/client_worker_common_api.cpp
    auto rc = RetryOnError(
        timeoutMs,
        [this, &req, &rsp](int32_t realRpcTimeout) {
            // ...
            return commonWorkerSession_->RegisterClient(opts, req, rsp);
        },
        []() { return Status::OK(); },
        { StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
          StatusCode::K_RPC_UNAVAILABLE },
        rpcTimeoutMs_);
    // ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(rc, "Register client failed");
    PostRegisterClient(timeoutMs, rsp);
    return Status::OK();
}
```

**结论（Client↔Worker TCP）**

- **有**：首次 `RegisterClient` 失败会向上返回错误，`Init` 失败（见下）；RPC 层重试码在 `RetryOnError` 中处理。
- **缺**：没有单独的「TCP 建链失败 → 退避 / 熔断 / 指标」模块；行为分散在 brpc 通道、`RetryOnError` 与日志中。
- **缺**：**首包 RPC 前**若底层 TCP 长期不可达，表现主要为超时/重试耗尽后的错误码，**无**与产品文档对齐的「建链阶段」显式状态机说明（需靠运维与日志推断）。

### 1.2 UB / 快路径：`FastTransportHandshake` 失败**不**导致 `RegisterClient` 失败

注册成功后 `PostRegisterClient` 调用 `FastTransportHandshake`；失败时仅用 `LOG_IF_ERROR` 打日志，**不改变** `RegisterClient` 已返回成功的结果 → **业务上视为「仍可用 TCP」**。

证据：

```801:822:src/datasystem/client/client_worker_common_api.cpp
void ClientWorkerRemoteCommonApi::PostRegisterClient(int32_t timeoutMs, const RegisterClientRspPb &rsp)
{
    // ...
    LOG_IF_ERROR(FastTransportHandshake(rsp), "Fast transport handshake failed, fall back to TCP/IP communication.");
}
```

`LOG_IF_ERROR` 语义（**吞掉错误，只打 ERROR 日志**）：

```138:145:src/datasystem/common/util/status_helper.h
#define LOG_IF_ERROR(statement_, msg_)                                                                               \
    do {                                                                                                             \
        Status rc_ = (statement_);                                                                                   \
        if (rc_.IsError()) {                                                                                         \
            std::string msg(msg_);                                                                                   \
            LOG(ERROR) << msg << ((!msg.empty() && msg.back() == '.') ? " " : ". ") << "Detail: " << rc_.ToString(); \
        }                                                                                                            \
    } while (false)
```

客户端 URMA 握手路径（`USE_URMA`）在 `FastTransportHandshake` 内：`InitializeFastTransportManager`、`ExecOnceParrallelExchange`、`ExchangeJfr` 任一步失败都会 `RETURN_IF_NOT_OK`，最终被上面 `LOG_IF_ERROR` 吸收。

证据：

```824:863:src/datasystem/client/client_worker_common_api.cpp
Status ClientWorkerRemoteCommonApi::FastTransportHandshake(const RegisterClientRspPb &rsp)
{
    SetClientFastTransportMode(rsp.fast_transport_mode(), fastTransportMemSize_);
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(InitializeFastTransportManager(hostPort_), "Fast transport init failed");
    if (IsShmEnable()) {
        FLAGS_enable_urma = false;
        return Status::OK();
    }
#ifdef USE_URMA
    if (UrmaManager::IsUrmaEnabled()) {
        // ...
        RETURN_IF_NOT_OK(constAccApi->second->ExecOnceParrallelExchange(handshakeRsp));
        if (handshakeRsp.has_hand_shake()) {
            RETURN_IF_NOT_OK(ExchangeJfr(handshakeRsp.hand_shake(), dummyRsp));
        }
    }
#endif
    return Status::OK();
}
```

**结论（Client↔Worker UB）**

- **有**：UB/URMA 握手失败时，日志明确写了 *fall back to TCP/IP* 的意图。
- **缺**：**无**向业务层暴露的「快路径不可用」状态（无指标、无回调、无统一枚举）；排障依赖日志。
- **缺**：**无**独立「UB 建链失败重试 / 冷却 / 与 TCP 并行的健康探测」策略文档与代码聚合点（逻辑散落在 `UrmaManager`、握手 RPC、`LOG_IF_ERROR`）。

### 1.3 初始化失败时的行为

`ObjectClientImpl::InitClientWorkerConnect` 中 `workerApi->Init(...)` 失败会直接 `RETURN_IF_NOT_OK`，**整个客户端初始化失败**，没有「仅 TCP 降级后再 Init」的第二套入口（与 1.2 中「注册已成功后的 UB 失败只打日志」是不同阶段）。

证据：

```334:348:src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::InitClientWorkerConnect(bool enableHeartbeat, bool initWithWorker)
{
    // ...
    RETURN_IF_NOT_OK(workerApi->Init(requestTimeoutMs_, connectTimeoutMs_, fastTransportMemSize_));
    mmapManager_ = std::make_unique<client::MmapManager>(workerApi, initWithWorker);
    // ...
}
```

断线后 **Reconnect** 使用 **1s** 超时再次走 `Connect`（与首次 `connectTimeoutMs_` 分离），仍无单独「建链失败」状态机说明。

证据：

```790:798:src/datasystem/client/client_worker_common_api.cpp
Status ClientWorkerRemoteCommonApi::Reconnect()
{
    LOG(INFO) << "Reconnect starting...";
    const int32_t reconnectTimeout = 1 * 1000;  // 1s for reconnect.
    RegisterClientReqPb req;
    RETURN_IF_NOT_OK(Connect(req, reconnectTimeout, true));
    // ...
}
```

---

## 2. Worker ↔ Worker

### 2.1 TCP（及 RPC）路径：`RpcStubCacheMgr::GetStub` + `GetObjectRemote` / 流式 RPC

Worker 拉远端数据时，先 `CreateRemoteWorkerApi` → `WorkerRemoteWorkerOCApi::Init` → `GetStub(hostPort_, StubType::WORKER_WORKER_OC_SVC, ...)`。**GetStub 或 Init 失败**会直接返回错误（无统一「建链失败」封装，错误信息分散）。

证据：

```56:62:src/datasystem/worker/object_cache/worker_worker_oc_api.cpp
Status WorkerRemoteWorkerOCApi::Init()
{
    std::shared_ptr<RpcStubBase> rpcStub;
    RETURN_IF_NOT_OK(RpcStubCacheMgr::Instance().GetStub(hostPort_, StubType::WORKER_WORKER_OC_SVC, rpcStub));
    rpcSession_ = std::dynamic_pointer_cast<WorkerWorkerOCService_Stub>(rpcStub);
    RETURN_RUNTIME_ERROR_IF_NULL(rpcSession_);
    return Status::OK();
}
```

实际拉数 `PullObjectDataFromRemoteWorker` 使用 `RetryOnErrorRepent`，对 `K_TRY_AGAIN`、`K_RPC_DEADLINE_EXCEEDED`、`K_RPC_UNAVAILABLE` 等重试；**TCP/RPC 失败**与 **UB 需重连** 在同一段重试循环里通过 `TryReconnectRemoteWorker` 耦合。

证据：

```1026:1083:src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp
Status WorkerOcServiceGetImpl::PullObjectDataFromRemoteWorker(const std::string &address, uint64_t dataSize,
                                                              ReadObjectKV &objectKV)
{
    // ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(CreateRemoteWorkerApi(address, akSkManager_, workerStub),
                                     "Create remote worker api failed.");
    // ...
    do {
        // ...
        Status rc = RetryOnErrorRepent(
            timeoutMs,
            [&workerStub, &reqPb, &rspPb, &clientApi, &address, this](int32_t) {
                RETURN_IF_NOT_OK(workerStub->GetObjectRemote(&clientApi));
                RETURN_IF_NOT_OK(workerStub->GetObjectRemoteWrite(clientApi, reqPb));
                auto rc = clientApi->Read(rspPb);
                RETURN_IF_NOT_OK(TryReconnectRemoteWorker(address, rc));
                return Status::OK();
            },
            // ...
            { StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
              StatusCode::K_RPC_UNAVAILABLE });
```

**结论（Worker↔Worker TCP/RPC）**

- **有**：RPC 超时上限、重试码集合、与业务读路径绑定的重试循环。
- **缺**：**无**「对端 Worker 不可达」与「本机 Stub 未创建」分离的显式错误分类；**无**文档化的建链阶段与数据阶段超时预算拆分（部分在注释/除法里体现，非统一机制）。

### 2.2 UB / URMA 交换路径：`WorkerRemoteWorkerTransApi` + `ExecOnceParrallelExchange`

Worker↔Worker 的 URMA 信息交换走 `WorkerWorkerTransportService`，`ExchangeUrmaConnectInfo` 内部是 **RPC** `WorkerWorkerExchangeUrmaConnectInfo`。

证据：

```98:122:src/datasystem/worker/object_cache/worker_worker_transport_api.cpp
Status WorkerRemoteWorkerTransApi::Init()
{
    std::shared_ptr<RpcStubBase> rpcStub;
    RETURN_IF_NOT_OK(RpcStubCacheMgr::Instance().GetStub(hostPort_, StubType::WORKER_WORKER_TRANS_SVC, rpcStub));
    rpcSession_ = std::dynamic_pointer_cast<WorkerWorkerTransportService_Stub>(rpcStub);
    RETURN_RUNTIME_ERROR_IF_NULL(rpcSession_);
    return Status::OK();
}

Status WorkerRemoteWorkerTransApi::ExchangeUrmaConnectInfo(UrmaHandshakeRspPb &rsp)
{
    // ...
    RETURN_IF_NOT_OK(rpcSession_->WorkerWorkerExchangeUrmaConnectInfo(opts, req, rsp));
    return Status::OK();
}
```

多线程并发握手时，`ExecOnceParrallelExchange` 用互斥 + 条件变量保证**单飞**；**失败**时 `notify_one` 让其它线程重试，**成功**则 `notify_all`。这是**并发合并**逻辑，不是业务级「建链失败熔断」。

证据：

```35:71:src/datasystem/worker/object_cache/worker_worker_transport_api.cpp
Status WorkerWorkerTransportApi::ExecOnceParrallelExchange(UrmaHandshakeRspPb &rsp)
{
    // ...
    auto result = ExchangeUrmaConnectInfo(rsp);
    // ...
    if (result.IsOk()) {
        globalStopFlag_ = true;
        cv_.notify_all();
    } else {
        cv_.notify_one();
    }
    return result;
}
```

读路径上，仅当 `Read` 返回 **`K_URMA_NEED_CONNECT`** 时，`TryReconnectRemoteWorker` 会再次执行 `ExecOnceParrallelExchange`，并返回 `K_TRY_AGAIN` 触发上层重试。

证据：

```914:936:src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp
Status WorkerOcServiceGetImpl::TryReconnectRemoteWorker(const std::string &endPoint, Status &lastResult)
{
    if (lastResult.IsOk() || lastResult.GetCode() != K_URMA_NEED_CONNECT) {
        return lastResult;
    }
    // ...
    RETURN_IF_NOT_OK(constAccApi->second->ExecOnceParrallelExchange(dummyRsp));
    RETURN_STATUS(K_TRY_AGAIN, "Reconnect success");
}
```

**结论（Worker↔Worker UB）**

- **有**：依赖 **TCP/RPC 先通** 才能完成 URMA 交换；`K_URMA_NEED_CONNECT` 时有**再握手 + TRY_AGAIN** 路径。
- **缺**：**无**「UB 建链失败 → 长期降级纯 RPC 载荷」的集中策略说明（与 client 侧类似，快路径失败分散在 URMA 层与读路径）；**无**与监控产品对齐的「建链成功率 / 握手耗时」专用埋点（从本文件可见范围看）。

---

## 3. 总表：现有行为 vs 设计缺口

| 链路 | 已有（代码层） | 缺口（设计/可观测/统一策略） |
|------|----------------|------------------------------|
| Client↔Worker TCP + Register | `RetryOnError`；失败则 Init 失败 | 无统一「建链阶段」状态机文档与指标；无熔断/退避与业务 SLA 对齐说明 |
| Client↔Worker SHM/UDS 辅助 | 失败记录并 **falling back to TCP**；mustUds 时硬失败 | 无面向运维的「何时 mustUds、如何修」一页纸；与心跳类型耦合需文档化 |
| Client↔Worker UB | 握手失败 **LOG_IF_ERROR**，Register 仍成功 | **无**业务可见的 fast-path 健康；无重试/冷却聚合；排障靠 ERROR 日志 |
| Worker↔Worker TCP/RPC | `GetStub` + `RetryOnErrorRepent` | 无「建链 vs 读数据」两阶段错误分型；CreateRemoteWorkerApi 失败与 RPC 失败混在同一上层处理 |
| Worker↔Worker UB | `K_URMA_NEED_CONNECT` → 再 `ExecOnceParrallelExchange` | 无 UB 长期不可用时的统一降级声明；无与 client 侧握手策略对称的说明 |

---

## 4. 建议（若补「设计」文档/实现）

1. **Client UB 握手失败**：除日志外，增加 **指标**（计数/最后一次错误码）、可选 **回调或状态查询**（`IsFastTransportActive()`），与文档「默认 TCP、UB 最佳努力」一致。  
2. **Worker↔Worker**：在 `CreateRemoteWorkerApi` / `GetStub` 失败与 `GetObjectRemote` 失败之间，明确 **错误码分层**（地址不可解析 / 连接拒绝 / 超时 / URMA 专用）。  
3. **统一一页**：`connectTimeoutMs`、Reconnect 1s、UB 握手与 `K_URMA_NEED_CONNECT` 重试的关系，写成与 **fault_handling** 系列 PlantUML 同级的说明，避免「设计里缺少处理机制」的歧义（实现有碎片，文档未收口）。

---

## 5. 相关文件索引

| 主题 | 路径 |
|------|------|
| Client Connect / Register / Reconnect / FastTransport | `src/datasystem/client/client_worker_common_api.cpp` |
| Client Init 失败传播 | `src/datasystem/client/object_cache/object_client_impl.cpp` |
| LOG_IF_ERROR 语义 | `src/datasystem/common/util/status_helper.h` |
| Worker↔Worker OC RPC | `src/datasystem/worker/object_cache/worker_worker_oc_api.cpp` |
| Worker↔Worker URMA 交换 RPC | `src/datasystem/worker/object_cache/worker_worker_transport_api.cpp` |
| 远端拉数 + URMA 重连 | `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` |
