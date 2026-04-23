# 代码证据：URMA 层故障检测与定位

## 1. URMA_NEED_CONNECT 检测与定位

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `urma_manager.cpp` | 1385-1413 | `CheckUrmaConnectionStable` |
| `worker_oc_service_get_impl.cpp` | 933-967 | `TryReconnectRemoteWorker` |
| `fast_transport_manager_wrapper.cpp` | 252 | 调用 `CheckUrmaConnectionStable` |

### 关键代码片段

**检测点 1: CheckUrmaConnectionStable**
```cpp
// urma_manager.cpp:1385-1413
Status UrmaManager::CheckUrmaConnectionStable(const std::string &hostAddress, const std::string &instanceId)
{
    TbbUrmaConnectionMap::const_accessor constAccessor;
    auto res = urmaConnectionMap_.find(constAccessor, hostAddress);
    if (!res) {
        LOG_FIRST_AND_EVERY_N(WARNING, K_URMA_WARNING_LOG_EVERY_N)
            << "[URMA_NEED_CONNECT] No existing connection for remoteAddress: " << hostAddress
            << ", remoteInstanceId=" << (instanceId.empty() ? "UNKNOWN" : instanceId) << ", requires creation.";
        RETURN_STATUS(K_URMA_NEED_CONNECT, "No existing connection requires creation.");
    }
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(
        constAccessor->second != nullptr, K_RUNTIME_ERROR,
        FormatString("Urma connection is null. remoteAddress=%s, remoteInstanceId=%s", hostAddress.c_str(),
                     instanceId.empty() ? "UNKNOWN" : instanceId.c_str()));
    if (!instanceId.empty()) {
        const auto &cachedInstanceId = constAccessor->second->GetUrmaJfrInfo().uniqueInstanceId;
        if (cachedInstanceId != instanceId) {
            LOG_FIRST_AND_EVERY_N(WARNING, K_URMA_WARNING_LOG_EVERY_N)
                << "[URMA_NEED_CONNECT] Connection stale for remoteAddress: " << hostAddress
                << ", cachedRemoteInstanceId=" << cachedInstanceId << ", requestRemoteInstanceId=" << instanceId
                << ", need reconnect.";
            RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect has disconnected and needs to be reconnected!");
        }
        return Status::OK();
    }
    LOG_FIRST_AND_EVERY_N(WARNING, K_URMA_WARNING_LOG_EVERY_N)
        << "[URMA_NEED_CONNECT] Connection unstable for remoteAddress: " << hostAddress
        << ", remoteInstanceId=UNKNOWN, need to reconnect.";
    RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect unstable, need to reconnect!");
}
```

**检测点 2: TryReconnectRemoteWorker**
```cpp
// worker_oc_service_get_impl.cpp:933-967
Status WorkerOcServiceGetImpl::TryReconnectRemoteWorker(const std::string &endPoint, Status &lastResult)
{
    if (lastResult.IsOk() || lastResult.GetCode() != K_URMA_NEED_CONNECT) {
        return lastResult;
    }

    std::string remoteWorkerId = "UNKNOWN";
    if (etcdCM_ != nullptr) {
        auto workerId = etcdCM_->GetWorkerIdByWorkerAddr(endPoint);
        if (!workerId.empty()) {
            remoteWorkerId = workerId;
        }
    }
    LOG_FIRST_AND_EVERY_N(WARNING, K_URMA_WARNING_LOG_EVERY_N)
        << "[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered, remoteAddress=" << endPoint
        << ", remoteWorkerId=" << remoteWorkerId << ", lastResult=" << lastResult.ToString();

    HostPort hostAddress;
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(hostAddress.ParseString(endPoint), "ParseString failed");

    TbbTransportStubTable::const_accessor constAccApi;
    while (!tarnsportApiTable_.find(constAccApi, endPoint)) {
        TbbTransportStubTable::accessor acc;
        if (tarnsportApiTable_.insert(acc, endPoint)) {
            std::shared_ptr<WorkerRemoteWorkerTransApi> transportApi =
                std::make_shared<WorkerRemoteWorkerTransApi>(hostAddress);
            RETURN_IF_NOT_OK_PRINT_ERROR_MSG(transportApi->Init(), "Create transport api faild.");
            acc->second = std::move(transportApi);
        }
    }

    UrmaHandshakeRspPb dummyRsp;
    RETURN_IF_NOT_OK(constAccApi->second->ExecOnceParrallelExchange(dummyRsp));
    RETURN_STATUS(K_TRY_AGAIN, "Reconnect success");
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_URMA_NEED_CONNECT (1006) | 连接需重建 | 连接不存在/实例不匹配/不稳定 |
| K_TRY_AGAIN (19) | 重试 | 重连成功后返回，触发重试框架 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `[URMA_NEED_CONNECT] No existing connection` | 连接不存在 | 需新建连接 |
| `[URMA_NEED_CONNECT] Connection stale` | 实例ID不匹配 | 需重连 |
| `[URMA_NEED_CONNECT] Connection unstable` | 实例ID未知 | 需重连 |
| `[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered` | 触发重连流程 | 正常恢复流程 |

### 调用链
```
Client GetRequest
  → TryGetObjectFromRemote
    → PullObjectDataFromRemoteWorker / BatchGetObjectFromRemoteWorker
      → GetObjectRemoteImpl (Worker2)
        → CheckUrmaConnectionStable (if unstable)
          → return K_URMA_NEED_CONNECT
      → Read(rsp) on Worker1
        → K_URMA_NEED_CONNECT
          → TryReconnectRemoteWorker
            → ExecOnceParrallelExchange (重建连接)
            → return K_TRY_AGAIN
          → RetryOnErrorRepent 重试整个 RPC
```

---

## 2. URMA_RECREATE_JFS 检测与定位

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `urma_manager.cpp` | 760-790 | `OnUrmaSendEvent` |
| `urma_manager.cpp` | 62-73 | `GetUrmaErrorHandlePolicy` |
| `urma_resource.cpp` | 370-407 | JFS 重建逻辑 |

### 关键代码片段

```cpp
// urma_manager.cpp:760-790
Status UrmaManager::OnUrmaSendEvent(const std::shared_ptr<UrmaConnection> &connection, uint64_t requestId,
                                    std::weak_ptr<UrmaEvent> event)
{
    RETURN_OK_IF_TRUE(!event->IsFailed());

    const auto statusCode = event->GetStatusCode();
    const auto policy = GetUrmaErrorHandlePolicy(statusCode);  // statusCode=9 → RECREATE_JFS
    const auto opName = UrmaEvent::OperationTypeName(event->GetOperationType());
    const auto &remoteAddr = event->GetRemoteAddress();
    const auto &remoteInstanceId = event->GetRemoteInstanceId();
    const auto requestIdStr = std::to_string(static_cast<uint64_t>(requestId));
    auto errMsg = FormatString("Polling failed with an error for requestId: %s, cqe status: %d", requestIdStr.c_str(),
                               statusCode);
    if (policy == UrmaErrorHandlePolicy::RECREATE_JFS) {
        LOG_FIRST_AND_EVERY_N(WARNING, K_URMA_WARNING_LOG_EVERY_N)
            << "[URMA_RECREATE_JFS] requestId=" << requestId << ", op=" << opName
            << ", remoteAddress=" << remoteAddr << ", remoteInstanceId=" << remoteInstanceId << ", cqeStatus=" << statusCode;
        auto connection = event->GetConnection().lock();
        auto oldJfs = event->GetJfs().lock();
        if (connection != nullptr) {
            LOG_IF_ERROR(connection->ReCreateJfs(*urmaResource_, oldJfs),
                         FormatString("[URMA_RECREATE_JFS_FAILED] requestId=%s, op=%s, remoteAddress=%s, "
                                      "remoteInstanceId=%s",
                                      requestIdStr.c_str(), opName, remoteAddr.c_str(), remoteInstanceId.c_str()));
        } else {
            LOG_FIRST_AND_EVERY_N(WARNING, K_URMA_WARNING_LOG_EVERY_N)
                << "[URMA_RECREATE_JFS_SKIP] Event connection expired, requestId=" << requestId << ", op=" << opName
                << ", remoteAddress=" << remoteAddr << ", remoteInstanceId=" << remoteInstanceId;
        }
    }

    return Status(K_URMA_ERROR, errMsg);
}

// urma_manager.cpp:62-73
UrmaErrorHandlePolicy GetUrmaErrorHandlePolicy(int statusCode)
{
    static std::unordered_map<int, UrmaErrorHandlePolicy> urmaErrorHandlePolicyTable = {
        { 9, UrmaErrorHandlePolicy::RECREATE_JFS },
    };

    const auto iter = urmaErrorHandlePolicyTable.find(statusCode);
    if (iter == urmaErrorHandlePolicyTable.end()) {
        return UrmaErrorHandlePolicy::DEFAULT;
    }
    return iter->second;
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_URMA_ERROR (1004) | URMA错误 | 通用URMA错误 |
| 内部错误码 9 | RECREATE_JFS | 触发JFS重建策略 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `[URMA_RECREATE_JFS] requestId=xxx, op=xxx, remoteAddress=xxx, cqeStatus=9` | JFS重建触发 | 自动重建，正常恢复 |
| `[URMA_RECREATE_JFS_FAILED] requestId=xxx` | 重建失败 | 需人工介入 |
| `[URMA_RECREATE_JFS_SKIP] Event connection expired` | 连接已过期 | 跳过重建，等待重连 |

---

## 3. URMA 初始化失败检测

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `urma_manager.cpp` | 189-234 | `Init` |
| `urma_dlopen_util.cpp` | - | dlopen 加载驱动 |

### 关键代码片段

```cpp
// urma_manager.cpp:189-234
Status UrmaManager::Init(const HostPort &hostport)
{
    PerfPoint perfPoint(PerfKey::URMA_MANAGER_INIT);
    InitState expected = InitState::UNINITIALIZED;
    if (initState_.compare_exchange_strong(expected, INITIALIZED)) {
        LOG(INFO) << "UrmaManager initializing local URMA resources"
                  << (hostport.Empty() ? "" : FormatString(", hostport = %s", hostport.ToString()));
    } else {
        // Initialization is already in progress or done by other thread, just wait for it to be done.
        waitInit_.Wait();
        return initState_ == INITIALIZED ? Status::OK() : Status(K_URMA_ERROR, "UrmaManager initialization failed");
    }
    RETURN_IF_NOT_OK(UrmaInit());
    // ... 设备初始化
}

// urma_dlopen_util.cpp - dlopen 失败
if (dlopen(lib路径, RTLD_NOW) == nullptr) {
    LOG(ERROR) << "dlopen failed: " << dlerror();
    RETURN_STATUS(K_URMA_ERROR, "Failed to load urma driver");
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_URMA_ERROR (1004) | URMA初始化失败 | UrmaManager initialization failed |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `UrmaManager initializing local URMA resources` | 初始化开始 | - |
| `UrmaManager initialization failed` | 初始化失败 | 检查UB驱动部署 |
| `dlopen failed: ...` | 驱动加载失败 | 检查 /usr/lib64/urma 目录 |

### 检查命令
```bash
lsmod | grep udma
urma_admin show -a  # 查看UB设备是否存在
```

---

## 4. CQ Poll/Wait/Rearm 失败检测

### 代码路径
| 文件 | 函数 |
|------|------|
| `urma_manager.cpp` | `urma_poll_jfc`, `urma_wait_jfc` |

### 错误码映射
| URMA接口 | 错误返回值 | errno | 故障原因 |
|----------|----------|-------|---------|
| urma_poll_jfc | -1 | UDMA_INTER_ERR | cqe为空、cqe解析失败 |
| urma_wait_jfc | -1 | ERR_PTR(512) | UDMA中断未上报、wait被中断 |
| urma_rearm_jfc | URMA_EINVAL | NA | 参数检查错误 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `Failed to poll jfc` | poll失败 | 重建CQ |
| `Failed to wait jfc` | wait超时 | 重试 |
| `poll jfc` 超时 (errno 512) | UDMA中断打断wait | 正常恢复 |

---

## 5. UB 直发失败降级 TCP

### 代码路径
| 文件 | 函数 |
|------|------|
| `fast_transport_manager_wrapper.cpp` | `WaitFastTransportEvent` |
| `worker_oc_service_get_impl.cpp` | `PullObjectDataFromRemoteWorker` |

### 关键代码片段

```cpp
// fast_transport_manager_wrapper.cpp
// 当 UB 不可用时，自动降级到 TCP
if (ubUnavailable) {
    LOG(INFO) << "UB unavailable, fallback to TCP";
    return Status(K_URMA_ERROR, "UB unavailable");
}
```

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `fallback to TCP/IP payload` | UB降级TCP | 正常降级，无需干预 |
| `UB payload overflow` | payload尺寸超限 | 检查数据大小 |

---

## 6. 恢复机制汇总

| 故障模式 | 错误码 | 恢复方法 | 代码位置 |
|---------|--------|---------|---------|
| K_URMA_NEED_CONNECT | 1006 | TryReconnectRemoteWorker → K_TRY_AGAIN → RetryOnErrorRepent | worker_oc_service_get_impl.cpp:933 |
| URMA_RECREATE_JFS | 1004 | connection->ReCreateJfs() | urma_manager.cpp:778 |
| UB初始化失败 | 1004 | 降级到TCP | fast_transport_manager_wrapper.cpp |
| CQ poll失败 | 1004 | 重建CQ | urma_manager.cpp |
| UB直发失败 | - | 自动降级TCP | fast_transport_manager_wrapper.cpp |

---

## 7. 代码验证汇总

| 故障检测点 | 文件位置 | 行号 | 验证状态 | 日志关键字 |
|-----------|---------|------|---------|-----------|
| CheckUrmaConnectionStable | urma_manager.cpp | 1385-1413 | ✅ 已验证 | `[URMA_NEED_CONNECT] No existing connection` |
| TryReconnectRemoteWorker | worker_oc_service_get_impl.cpp | 933-967 | ✅ 已验证 | `[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered` |
| OnUrmaSendEvent | urma_manager.cpp | 760-790 | ✅ 已验证 | `[URMA_RECREATE_JFS] cqeStatus=9` |
| GetUrmaErrorHandlePolicy | urma_manager.cpp | 62-73 | ✅ 已验证 | cqeStatus=9 → RECREATE_JFS |
| UB fallback | client_worker_base_api.cpp | 118, 132 | ✅ 已验证 | `fallback to TCP/IP payload` |