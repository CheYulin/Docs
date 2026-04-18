# 04a · 接口级故障树：Init / MCreate / MSet / MGet

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/client/kv_cache/kv_client.cpp` | `KVClient` 接口入口 |
| `src/datasystem/client/object_cache/object_client_impl.cpp` | 核心实现 |
| `src/datasystem/client/object_cache/object_client_impl.h` | 接口声明 |
| `src/datasystem/client/listen_worker.cpp` | 心跳与断连检测 |
| `src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp` | `RETRY_ERROR_CODE` 定义与重试策略 |
| `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` | Worker 端 Get 实现 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | 远端读 URMA 路径 |

> 本仓 KV 接口仅有 Publish，**无 `MPublish`**；对应的批量发布是 `MSet(buffers)` / `ObjectClientImpl::MultiPublish`。

---

## 1. 接口与错误码映射总表

| 接口 | 入口函数 | 成功码 | 主要错误码 | 错误码来源 |
|------|---------|--------|-----------|-----------|
| Init | `KVClient::Init()`（`kv_client.cpp:67`） | `K_OK` | `K_INVALID`、`K_RPC_UNAVAILABLE`、`K_CLIENT_WORKER_DISCONNECT` | `IsClientReady()`、`InitClientWorkerConnect()` |
| MCreate | `KVClient::MCreate()`（`kv_client.cpp:120`） | `K_OK` | `K_INVALID`、`K_RUNTIME_ERROR`（mmap 失败）、`K_DUPLICATED` | `IsClientReady()`、`MultiCreate()` |
| MSet (Buffer) | `KVClient::MSet(buffers)`（`kv_client.cpp:159`） | `K_OK` | `K_INVALID`（空列表）、`K_RUNTIME_ERROR` | `impl_->MSet(buffers)` |
| MSet (kv) | `KVClient::MSet(keys, vals)`（`kv_client.cpp:358`） | `K_OK` | `K_INVALID`、`K_RPC_UNAVAILABLE`、`K_TRY_AGAIN` | `GetAvailableWorkerApi()`、`MultiPublish()` |
| MGet | `KVClient::Get(keys)`（`kv_client.cpp:194`） | `K_OK` | `K_INVALID`、`K_NOT_FOUND`、`K_RPC_UNAVAILABLE`、`K_RUNTIME_ERROR`、`K_URMA_*` | `impl_->Get()` → `GetBuffersFromWorker()` |

---

## 2. 故障分析树（按码展开）

```text
SDK 错误码
│
├── K_INVALID (2)
│   └── 根因: 参数错误 / 客户端未初始化
│       证据: kv_client.cpp:132 "IsClientReady()" → K_NOT_READY
│       证据: kv_client.cpp:2882-2888 参数校验
│
├── K_CLIENT_WORKER_DISCONNECT (23)
│   └── 根因: Worker 进程退出 / 网络断开 / 心跳超时
│       证据: listen_worker.cpp "Cannot receive heartbeat from worker"
│       证据: client_worker_common_api.cpp fd 交换失败 → 1002
│
├── K_NOT_READY (8)
│   └── 根因: 客户端未调用 Init() 或 Init() 失败
│       证据: object_client_impl.cpp:778-781 IsClientReady()
│
├── K_RPC_UNAVAILABLE (1002)
│   ├── 根因: TCP / ZMQ 建连失败
│   │   证据: zmq_stub_conn.cpp "Network unreachable"
│   │   证据: zmq_stub_conn.cpp "Timeout waiting for SockConnEntry wait"
│   ├── 根因: socket reset (EPIPE / ECONNRESET)
│   │   证据: unix_sock_fd.cpp ErrnoToStatus "Connect reset"
│   ├── 根因: fd 交换 (SHM) 失败
│   │   证据: client_worker_common_api.cpp "shm fd transfer"
│   └── 根因: 心跳不可写
│       证据: zmq_stub_conn.cpp "ZMQ_POLLOUT not writable"
│
├── K_RPC_DEADLINE_EXCEEDED (1001)
│   └── 根因: RPC 超时 / 对端未响应
│       证据: rpc_util.h IsRpcTimeout()
│
├── K_URMA_ERROR (1004)
│   └── 根因: URMA 传输操作失败（远端读场景）
│       证据: urma_manager.cpp CheckUrmaConnectionStable()
│       证据: worker_worker_oc_service_impl.cpp "UrmaWritePayload error"
│
├── K_URMA_NEED_CONNECT (1006)
│   ├── 根因: URMA 连接不稳定 / 实例不匹配
│   │   证据: urma_manager.cpp CheckUrmaConnectionStable()
│   └── 处理: → TryReconnectRemoteWorker() → K_TRY_AGAIN
│       证据: worker_oc_service_get_impl.cpp TryReconnectRemoteWorker
│
├── K_URMA_TRY_AGAIN (1008)
│   └── 根因: URMA 瞬时可恢复故障
│       证据: 重试机制 RetryOnError
│
├── K_RUNTIME_ERROR (5)
│   ├── 根因: mmap 失败
│   │   证据: kv_client.cpp:135 "client fd mmap failed"
│   │   证据: object_client_impl.h:172
│   └── 根因: Worker 端处理错误
│       证据: WorkerOCServiceImpl 返回码传递
│
├── K_OUT_OF_MEMORY (6)
│   └── 根因: 客户端 / Worker 内存不足
│
├── K_NO_SPACE (13)
│   └── 根因: 磁盘空间不足 (spill 场景)
│       证据: worker_oc_spill.cpp "No space when WorkerOcSpill::Spill"
│
├── K_FILE_LIMIT_REACHED (18)
│   └── 根因: FD 数量达到上限
│
├── K_SCALE_DOWN (31)
│   ├── 根因: Worker 正在退出 / 缩容
│   │   证据: worker_oc_service_impl.cpp "Worker is exiting now"
│   │   证据: HealthCheck 返回 K_SCALE_DOWN
│   └── 场景: 运维变更 / 缩容操作
│
├── K_SCALING (32)
│   └── 根因: 集群扩缩容进行中
│
├── K_TRY_AGAIN (19)
│   ├── 根因: 临时性错误，可重试
│   │   证据: RetryOnError 重试间隔 1, 5, 50, 200, 1000, 5000 ms
│   └── 注意: 与 K_URMA_TRY_AGAIN (1008) 区分
│
└── K_NOT_FOUND (3)
    ├── 根因: Key 不存在
    │   证据: kv_client.cpp Get 返回 K_NOT_FOUND
    └── 注意: access log 中记为 K_OK（特殊处理）
        证据: kv_client.cpp:187 code = (rc == K_NOT_FOUND) ? K_OK : rc
```

---

## 3. Init 接口

### 3.1 调用链

```text
KVClient::Init()
  └─ ObjectClientImpl::Init()
       ├─ clientStateManager_->ProcessInit()
       ├─ serviceDiscovery_->SelectWorker()     [可选]
       ├─ RpcAuthKeyManager::CreateClientCredentials()
       └─ InitClientWorkerConnect()
            ├─ GetAvailableWorkerApi()
            ├─ ListenWorker::Start()             [心跳]
            └─ workerApi_->RegisterClient()      [注册]
```

### 3.2 错误码证据

| 错误码 | 触发位置 | 原因 |
|--------|---------|------|
| `K_INVALID` | `kv_client.cpp:421` | `ConnectOptions` 未配置 host/port 或 serviceDiscovery |
| `K_INVALID` | `kv_client.cpp:425-426` | IP 地址 / 端口格式无效 |
| `K_RPC_UNAVAILABLE` | `InitClientWorkerConnect` | 建连失败 |
| `K_CLIENT_WORKER_DISCONNECT` | `listen_worker.cpp` | 首次心跳超时 |

### 3.3 源码引用

**Init 入口**（`kv_client.cpp:67-74`）：

```cpp
Status KVClient::Init()
{
    TraceGuard traceGuard = Trace::Instance().SetTraceUUID();
    (void)metrics::InitKvMetrics();
    bool needRollbackState;
    auto rc = impl_->Init(needRollbackState, true);
    impl_->CompleteHandler(rc.IsError(), needRollbackState);
    return rc;
}
```

**Init 实现**（`object_client_impl.cpp:403-431`）：

```cpp
Status ObjectClientImpl::Init(bool &needRollbackState, bool enableHeartbeat)
{
    Logging::GetInstance()->Start(CLIENT_LOG_FILENAME, true);
    FlagsMonitor::GetInstance()->Start();

    auto rc = clientStateManager_->ProcessInit(needRollbackState);
    if (!needRollbackState) {
        return rc;
    }
    // ... host port 校验 ...
    RETURN_IF_NOT_OK(InitClientWorkerConnect(enableHeartbeat, false));
    return Status::OK();
}
```

---

## 4. MCreate 接口

### 4.1 调用链

```text
KVClient::MCreate()
  └─ ObjectClientImpl::MCreate()
       ├─ IsClientReady()
       ├─ Validator::IsBatchSizeUnderLimit()
       ├─ CheckValidObjectKey()                 [逐 key 校验]
       └─ MultiCreate()
            ├─ GetAvailableWorkerApi()
            ├─ workerApi_->MultiCreate()        [RPC 调用]
            └─ 分配共享内存 Buffer
```

### 4.2 错误码证据

| 错误码 | 触发位置 | 原因 |
|--------|---------|------|
| `K_INVALID` | `kv_client.cpp:2882` | `keys` 为空 |
| `K_INVALID` | `kv_client.cpp:2883-2884` | key 数量超限（2000） |
| `K_INVALID` | `kv_client.cpp:2885` | keys 与 sizes 数量不匹配 |
| `K_INVALID` | `kv_client.cpp:2887-2888` | key 为空或格式无效 |
| `K_RUNTIME_ERROR` | `kv_client.cpp:135` | client fd mmap 失败 |
| `K_DUPLICATED` | `object_client_impl.h:172` | key 已存在（NX 模式） |

### 4.3 源码引用

**MCreate 实现**（`object_client_impl.cpp:2878-2893`）：

```cpp
Status ObjectClientImpl::MCreate(const std::vector<std::string> &keys,
                                 const std::vector<uint64_t> &sizes,
                                 const FullParam &param,
                                 std::vector<std::shared_ptr<Buffer>> &buffers)
{
    RETURN_IF_NOT_OK(IsClientReady());
    CHECK_FAIL_RETURN_STATUS(keys.size() > 0, K_INVALID, "The keys should not be empty.");
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(Validator::IsBatchSizeUnderLimit(keys.size()), K_INVALID, ...);
    CHECK_FAIL_RETURN_STATUS(keys.size() == sizes.size(), K_INVALID, "The number of key and value is not the same.");
    for (size_t i = 0; i < keys.size(); ++i) {
        CHECK_FAIL_RETURN_STATUS(!keys[i].empty(), K_INVALID, "The key should not be empty.");
        RETURN_IF_NOT_OK(CheckValidObjectKey(keys[i]));
    }
    bool skipCheckExistence = param.existence != ExistenceOpt::NX;
    return MultiCreate(keys, sizes, param, skipCheckExistence, buffers, exist);
}
```

---

## 5. MSet 接口

### 5.1 调用链：MSet(buffers)

```text
KVClient::MSet(buffers)
  └─ ObjectClientImpl::MSet(buffers)
       ├─ IsClientReady()
       ├─ workerApi_->MultiPublish()
       └─ HandleShmRefCountAfterMultiPublish()
```

### 5.2 调用链：MSet(keys, vals)

```text
KVClient::MSet(keys, vals, outFailedKeys, param)
  └─ ObjectClientImpl::MSet(keys, vals, param, outFailedKeys)
       ├─ CheckMultiSetInputParamValidationNtx()
       ├─ GetAvailableWorkerApi()
       ├─ MultiCreate()                         [创建 Buffer]
       ├─ MemoryCopyParallel()                  [拷贝数据]
       └─ MultiPublish()                        [发布]
```

### 5.3 错误码证据

| 错误码 | 触发位置 | 原因 |
|--------|---------|------|
| `K_INVALID` | `kv_client.cpp:161` | `buffers` 为空 |
| `K_INVALID` | `kv_client.cpp:2881` | `keys` 为空 |
| `K_RPC_UNAVAILABLE` | `MultiPublish` | TCP / ZMQ 失败 |
| `K_TRY_AGAIN` | `RetryOnError` | 可重试错误 |
| `K_RUNTIME_ERROR` | `mmap / shm` 错误 | 共享内存操作失败 |

### 5.4 源码引用

**MSet(buffers) 入口**（`kv_client.cpp:159-172`）：

```cpp
Status KVClient::MSet(const std::vector<std::shared_ptr<Buffer>> &buffers)
{
    CHECK_FAIL_RETURN_STATUS(!buffers.empty(), K_INVALID, "Buffer list should not be empty.");
    // ...
    Status rc = impl_->MSet(buffers);
    METRIC_INC(metrics::KvMetricId::CLIENT_PUT_REQUEST_TOTAL);
    METRIC_ERROR_IF(rc.IsError(), metrics::KvMetricId::CLIENT_PUT_ERROR_TOTAL);
    return rc;
}
```

**MSet(keys, vals) 实现**（`object_client_impl.cpp:2931-2982`）：

```cpp
Status ObjectClientImpl::MSet(const std::vector<std::string> &keys,
                              const std::vector<StringView> &vals,
                              const MSetParam &param,
                              std::vector<std::string> &outFailedKeys)
{
    // ... 参数校验 ...
    std::shared_ptr<IClientWorkerApi> workerApi;
    std::unique_ptr<Raii> raii;
    RETURN_IF_NOT_OK(GetAvailableWorkerApi(workerApi, raii));
    // ... MultiCreate + MemoryCopy ...
    RETURN_IF_NOT_OK(workerApi->MultiPublish(bufferInfoList, publishParam, rsp));
    // ...
}
```

**MultiPublish 的重试码**：`client_worker_remote_api.cpp::MultiPublish` 显式把 `K_SCALING` 纳入重试集合：

```cpp
{ K_TRY_AGAIN, K_RPC_CANCELLED, K_RPC_DEADLINE_EXCEEDED,
  K_RPC_UNAVAILABLE, K_OUT_OF_MEMORY, K_SCALING }
```

---

## 6. MGet 接口

### 6.1 调用链

```text
KVClient::Get(keys)
  └─ ObjectClientImpl::Get()
       ├─ IsClientReady()
       ├─ GetAvailableWorkerApi()
       ├─ workerApi_->Get()                     [RPC 调用]
       │     └─ RetryOnError(RETRY_ERROR_CODE)  [重试逻辑]
       ├─ GetBuffersFromWorker()
       │     ├─ 本地: 直接返回 Buffer
       │     └─ 远端: Worker → Worker URMA 传输
       └─ ProcessGetResponse()
```

### 6.2 重试错误码集合

`RETRY_ERROR_CODE`（`client_worker_remote_api.cpp:36-38`）：

```cpp
{ K_TRY_AGAIN, K_RPC_CANCELLED, K_RPC_DEADLINE_EXCEEDED,
  K_RPC_UNAVAILABLE, K_OUT_OF_MEMORY }
```

### 6.3 错误码证据

| 错误码 | 触发位置 | 原因 |
|--------|---------|------|
| `K_INVALID` | `kv_client.cpp:435` | keys 数量超限 |
| `K_NOT_FOUND` | `GetBuffersFromWorker` | Key 不存在（access log 记为 `K_OK`，见 03 §3.4） |
| `K_RPC_UNAVAILABLE` | `stub_->Get()` | TCP / ZMQ 失败 |
| `K_RPC_DEADLINE_EXCEEDED` | RPC timeout | RPC 超时 |
| `K_URMA_ERROR` | `UrmaWritePayload` | URMA 传输失败 |
| `K_URMA_NEED_CONNECT` | `CheckUrmaConnectionStable` | URMA 需重连 |
| `K_RUNTIME_ERROR` | Worker 处理错误 | Worker 内部错误 |

### 6.4 源码引用

**MGet 实现**（`object_client_impl.cpp:1881-1920`）：

```cpp
Status ObjectClientImpl::Get(const std::vector<std::string> &objectKeys, int64_t subTimeoutMs,
                             std::vector<Optional<Buffer>> &buffers, bool queryL2Cache, bool isRH2DSupported)
{
    // ... 参数校验 ...
    std::shared_ptr<IClientWorkerApi> workerApi;
    std::unique_ptr<Raii> raii;
    RETURN_IF_NOT_OK(GetAvailableWorkerApi(workerApi, raii));

    // ... 获取 buffer ...
    Status rc = GetBuffersFromWorker(workerApi, getParam, buffers);
    if (rc.GetCode() == K_FUTURE_TIMEOUT || rc.GetCode() == K_RPC_DEADLINE_EXCEEDED) {
        LOG(ERROR) << "get request timeout, msg:" << rc.ToString();
        return Status(K_FUTURE_TIMEOUT, "can't find objects");
    }
    // ...
}
```

**远端读 URMA 路径**（`worker_worker_oc_service_impl.cpp`）：

- `serverApi->Read(req)` → `CheckConnectionStable(req)` → `GetObjectRemoteImpl()`
- URMA 分支：`UrmaWritePayload()` → `rsp.data_source = DATA_ALREADY_TRANSFERRED`

> Get 批量路径上 `K_SCALING` 可能只存在于 per-object `last_rc`，顶层 `Status` 可能为 `K_OK`。运维侧观察见 [06-playbook.md § 3](06-playbook.md)。

---

## 7. 定界决策树（按码值域）

```text
收到错误码
│
├─ 码 ∈ {2, 8}?
│   └─ 是 → 检查 Init() 是否成功调用，参数是否合法
│
├─ 码 ∈ {23, 31, 32}?
│   └─ 是 → 检查 Worker 生命周期状态（心跳 / 缩容 / 扩缩容）
│       ├─ 23: Worker 连接断开   → 查网络 / Worker 进程
│       ├─ 31: Worker 缩容中     → 运维变更记录
│       └─ 32: 扩缩容进行中      → 等待或切流量
│
├─ 码 ∈ {1001, 1002}?
│   └─ 是 → 检查 TCP / ZMQ 通道
│       ├─ ECONNRESET / EPIPE  → socket 异常
│       ├─ shm fd transfer      → fd 交换失败
│       └─ Network unreachable  → 网络不可达
│
├─ 码 ∈ {1004, 1006, 1008}?
│   └─ 是 → 检查 URMA 数据面
│       ├─ 1006 (NEED_CONNECT)  → TryReconnectRemoteWorker
│       ├─ 1008 (TRY_AGAIN)     → 重试成功?
│       └─ 1004 (ERROR)         → 检查 UB 链路
│
├─ 码 ∈ {6, 13, 18}?
│   └─ 是 → 检查系统资源
│       ├─ 6:  OOM             → 内存使用情况
│       ├─ 13: NO_SPACE         → 磁盘空间
│       └─ 18: FD_LIMIT         → 文件描述符
│
├─ 码 = 5 (RUNTIME_ERROR)?
│   └─ 是 → 检查 mmap / 共享内存操作；查 "client fd mmap failed" 日志
│
├─ 码 = 19 (TRY_AGAIN)?
│   └─ 是 → 可重试，等待或重试
│
└─ 码 = 3 (NOT_FOUND)?
    └─ 是 → Key 不存在，非系统错误
```

---

## 8. 责任域划分

| 错误类型 | 责任域 | 排查方向 |
|---------|--------|---------|
| `K_RPC_UNAVAILABLE` (1002) | OS 网络栈 / TCP.ZMQ | socket 状态、网络连通性 |
| `K_URMA_*` (1004 / 1006 / 1008) | UB / URMA 数据面 | URMA 连接状态、重连日志 |
| `K_CLIENT_WORKER_DISCONNECT` (23) | Worker 进程 | Worker 健康状态、心跳 |
| `K_SCALE_DOWN` / `K_SCALING` (31 / 32) | 运维操作 | 扩缩容变更记录 |
| `K_OUT_OF_MEMORY` / `K_NO_SPACE` / `K_FILE_LIMIT_REACHED` | OS 资源 | 内存 / 磁盘 / FD 使用率 |
| `K_RUNTIME_ERROR` (5) | DataSystem 内部 | mmap / shm 错误，Worker 日志 |
| `K_INVALID` (2) | 调用方 | 参数校验、客户端代码 |
